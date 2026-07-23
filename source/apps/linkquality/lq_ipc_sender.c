/**
 * lq_ipc_sender.c -- OneWifi (sender) side of the connected-performance IPC.
 *
 * Per-station payload is develop's stats_arg_t (wifi_base.h, pulled in by
 * run_qmgr.h): {mac_str, ap_mac_str, vap_index, radio_index, channel_utilization,
 * dev, ...}. Each entry is shipped RAW; the daemon reads the same staged struct,
 * so the wire stays in lock-step by construction. Only vap_index is referenced
 * here (for the private-VAP filter); channel_utilization is populated upstream by
 * the stats path (wifi_stats_assoc_client.c via get_radio_channel_utilization) and
 * consumed by the daemon's scorer. (Sanjay's rebased branch was reference only.)
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "lq_ipc_sender.h"
#include "wifi_mgr.h"     /* get_wifimgr_obj() */
#include "wifi_util.h"    /* is_vap_private(), wifi_util_*_print(), WIFI_APPS */
#include "run_qmgr.h"     /* stats_arg_t */

/* Cached datagram socket fd; reopened lazily and after a send failure that
 * indicates the receiver (wei) restarted and recreated its socket file. */
static int lq_ipc_fd = -1;

/* ---- dedicated OneWifi<->wei IPC/ConnPerf pathway log (tmpfs) -------------- */
#define LQ_IPC_LOG_PATH      "/tmp/onewifi_wei_ipc.log"
#define LQ_IPC_LOG_MAX_BYTES (8 * 1024 * 1024)

static pthread_mutex_t lq_ipc_log_lock = PTHREAD_MUTEX_INITIALIZER;
static FILE           *lq_ipc_log_fp;
static long            lq_ipc_log_bytes;

/* Append one timestamped line to the dedicated IPC log. Thread-safe (sender runs
 * on the ctrl/apps thread, the ConnPerf consumer on the bus-callback thread) and
 * size-capped so extensive logging on tmpfs can never exhaust RAM. */
void lq_ipc_debug_log(const char *fmt, ...)
{
    struct timespec ts;
    struct tm tm_buf;
    char stamp[32];
    char line[1024];
    int off, avail, n;
    va_list ap;

    if (fmt == NULL) {
        return;
    }

    clock_gettime(CLOCK_REALTIME, &ts);
    if (localtime_r(&ts.tv_sec, &tm_buf) != NULL &&
        strftime(stamp, sizeof(stamp), "%Y-%m-%d %H:%M:%S", &tm_buf) > 0) {
        off = snprintf(line, sizeof(line), "%s.%03ld ", stamp, ts.tv_nsec / 1000000L);
    } else {
        off = 0;
    }
    if (off < 0) off = 0;
    if (off > (int)sizeof(line) - 1) off = (int)sizeof(line) - 1;

    avail = (int)sizeof(line) - off;
    va_start(ap, fmt);
    n = vsnprintf(line + off, (size_t)avail, fmt, ap);
    va_end(ap);
    if (n > 0) off += (n < avail) ? n : (avail - 1);

    pthread_mutex_lock(&lq_ipc_log_lock);
    if (lq_ipc_log_fp == NULL) {
        lq_ipc_log_fp = fopen(LQ_IPC_LOG_PATH, "w");
        lq_ipc_log_bytes = 0;
    } else if (lq_ipc_log_bytes >= LQ_IPC_LOG_MAX_BYTES) {
        lq_ipc_log_fp = freopen(LQ_IPC_LOG_PATH, "w", lq_ipc_log_fp);
        lq_ipc_log_bytes = 0;
    }
    if (lq_ipc_log_fp != NULL && off > 0) {
        lq_ipc_log_bytes += (long)fwrite(line, 1, (size_t)off, lq_ipc_log_fp);
        fflush(lq_ipc_log_fp);
    }
    pthread_mutex_unlock(&lq_ipc_log_lock);
}

static void lq_ipc_reset_fd(void)
{
    if (lq_ipc_fd >= 0) {
        close(lq_ipc_fd);
        lq_ipc_fd = -1;
    }
}

static int lq_ipc_open_fd(void)
{
    if (lq_ipc_fd >= 0) {
        return 0;
    }
    lq_ipc_fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (lq_ipc_fd < 0) {
        wifi_util_error_print(WIFI_APPS,
            "%s:%d socket() failed: %s\n", __func__, __LINE__, strerror(errno));
        return -1;
    }
    /* Match the receiver's 4 MB SO_RCVBUF so bursts (50+ clients) are not
     * dropped locally. Best-effort: ignore failure. */
    int sndbuf = 4 * 1024 * 1024;
    (void)setsockopt(lq_ipc_fd, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof(sndbuf));
    return 0;
}

static const char *lq_msg_type_str(uint32_t type)
{
    switch (type) {
    case LQ_IPC_MSG_PERIODIC_STATS:   return "PERIODIC_STATS";
    case LQ_IPC_MSG_DISCONNECT:       return "DISCONNECT";
    case LQ_IPC_MSG_RAPID_DISCONNECT: return "RAPID_DISCONNECT";
    case LQ_IPC_MSG_REGISTER_STA:     return "REGISTER_STA";
    case LQ_IPC_MSG_UNREGISTER_STA:   return "UNREGISTER_STA";
    default:                          return "OTHER";
    }
}

/* build_tlv -- encode payload as a single packed TLV. Returns bytes written or -1. */
static int build_tlv(uint32_t msg_type, const void *entries,
                     uint32_t count, size_t entry_size,
                     uint8_t *buf, size_t buf_sz)
{
    size_t data_sz = (size_t)count * entry_size;
    size_t needed  = sizeof(lq_tlv_t) + data_sz;

    if (needed > buf_sz) {
        wifi_util_error_print(WIFI_APPS,
            "%s:%d [TLV] buffer too small: need %zu have %zu\n",
            __func__, __LINE__, needed, buf_sz);
        return -1;
    }
    if (data_sz > UINT16_MAX || entry_size > UINT16_MAX) {
        wifi_util_error_print(WIFI_APPS,
            "%s:%d [TLV] payload %zu / elem %zu exceeds uint16_t max\n",
            __func__, __LINE__, data_sz, entry_size);
        return -1;
    }

    lq_tlv_t *tlv = (lq_tlv_t *)buf;
    tlv->type      = (uint8_t)msg_type;
    tlv->version   = LQ_IPC_WIRE_VERSION;
    tlv->elem_size = (uint16_t)entry_size;
    tlv->len       = (uint16_t)data_sz;
    if (data_sz > 0 && entries != NULL) {
        memcpy(tlv->value, entries, data_sz);
    }
    return (int)needed;
}

int lq_ipc_send(uint32_t msg_type, const void *entries,
                uint32_t count, size_t entry_size)
{
    if (count != 0 && entries == NULL) {
        return -1;
    }

    /* Forward only private-VAP (private_ssid*) stats_arg_t events. */
    if (entry_size == sizeof(stats_arg_t) && count > 0) {
        wifi_mgr_t *mgr = get_wifimgr_obj();
        if (mgr != NULL) {
            const stats_arg_t *s = (const stats_arg_t *)entries;
            for (uint32_t i = 0; i < count; i++) {
                if (is_vap_private(&mgr->hal_cap.wifi_prop, s[i].vap_index) != TRUE) {
                    wifi_util_dbg_print(WIFI_APPS,
                        "%s:%d [IPC-SEND] drop %s: vap_index=%u not private\n",
                        __func__, __LINE__, lq_msg_type_str(msg_type), s[i].vap_index);
                    lq_ipc_debug_log("[IPC-SEND] DROP %s: vap_index=%u not private\n",
                        lq_msg_type_str(msg_type), s[i].vap_index);
                    return 0;
                }
            }
        }
    }

    if (lq_ipc_open_fd() < 0) {
        return -1;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, LQ_STATS_SOCKET_PATH, sizeof(addr.sun_path) - 1);

    size_t data_sz  = (size_t)count * entry_size;
    size_t alloc_sz = sizeof(lq_tlv_t) + data_sz;
    uint8_t *buf = (uint8_t *)malloc(alloc_sz);
    if (buf == NULL) {
        wifi_util_error_print(WIFI_APPS,
            "%s:%d malloc(%zu) failed\n", __func__, __LINE__, alloc_sz);
        return -1;
    }

    int tlv_len = build_tlv(msg_type, entries, count, entry_size, buf, alloc_sz);
    if (tlv_len < 0) {
        free(buf);
        return -1;
    }

    /* Retry once: if wei restarted, its socket file was recreated -- reset our
     * fd and reopen so the next sendto hits the fresh socket.
     *   ENOENT       -> socket file gone (wei not up / mid-restart)
     *   ECONNREFUSED -> peer end closed (stale DGRAM path)
     *   EAGAIN       -> receiver buffer full (wei slow to drain) */
    ssize_t ret = -1;
    for (int attempt = 0; attempt < 2; attempt++) {
        ret = sendto(lq_ipc_fd, buf, (size_t)tlv_len, MSG_DONTWAIT,
                     (struct sockaddr *)&addr, sizeof(addr));
        if (ret >= 0) {
            break;
        }
        if (errno == ENOENT || errno == ECONNREFUSED) {
            lq_ipc_reset_fd();
            if (lq_ipc_open_fd() < 0) {
                break;
            }
            continue;
        }
        break; /* EAGAIN and others: drop this datagram, non-fatal */
    }

    if (ret < 0) {
        wifi_util_info_print(WIFI_APPS,
            "%s:%d [IPC-SEND] %s DROPPED: %s\n",
            __func__, __LINE__, lq_msg_type_str(msg_type), strerror(errno));
        lq_ipc_debug_log("[IPC-SEND] %s DROPPED: %s\n",
            lq_msg_type_str(msg_type), strerror(errno));
    } else {
        wifi_util_info_print(WIFI_APPS,
            "%s:%d [IPC-SEND] sent %s count=%u bytes=%d -> %s\n",
            __func__, __LINE__, lq_msg_type_str(msg_type), count, tlv_len,
            LQ_STATS_SOCKET_PATH);
        lq_ipc_debug_log("[IPC-SEND] sent %s count=%u bytes=%d -> %s\n",
            lq_msg_type_str(msg_type), count, tlv_len, LQ_STATS_SOCKET_PATH);
    }

    free(buf);
    return (ret >= 0) ? 0 : -1;
}
