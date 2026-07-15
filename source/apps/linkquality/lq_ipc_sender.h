/**
 * lq_ipc_sender.h -- OneWifi (sender) side of the connected-performance IPC.
 *
 * Ships per-client link-quality stats/events from OneWifi's in-process
 * linkquality path to the standalone wei scorer daemon over an AF_UNIX
 * SOCK_DGRAM socket. This header defines the wire contract; it MUST stay
 * byte-for-byte consistent with the daemon receiver (weid_receiver.h):
 * same socket path, same message-type values, same TLV framing, same
 * per-station payload (stats_arg_t from run_qmgr.h).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef LQ_IPC_SENDER_H
#define LQ_IPC_SENDER_H
#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include <stddef.h>

/* AF_UNIX datagram socket shared with the wei scorer daemon (receiver). */
#define LQ_STATS_SOCKET_PATH "/tmp/linkquality_stats.sock"

/*
 * IPC message types. Full code space is defined for wire completeness; the
 * daemon acts only on PERIODIC_STATS, DISCONNECT, RAPID_DISCONNECT,
 * REGISTER_STA and UNREGISTER_STA. Values MUST match weid_receiver.h.
 */
#define LQ_IPC_MSG_PERIODIC_STATS    1
#define LQ_IPC_MSG_DISCONNECT        2
#define LQ_IPC_MSG_RAPID_DISCONNECT  3
#define LQ_IPC_MSG_CAFFINITY_EVENT   4
#define LQ_IPC_MSG_START_METRICS     5
#define LQ_IPC_MSG_STOP_METRICS      6
#define LQ_IPC_MSG_REGISTER_STA      7
#define LQ_IPC_MSG_UNREGISTER_STA    8
#define LQ_IPC_MSG_REINIT_METRICS    9
#define LQ_IPC_MSG_SET_MAX_SNR      10
#define LQ_IPC_MSG_SET_SCORE_PARAMS 11

/*
 * The whole datagram is one TLV: 1-byte type, 2-byte length, packed payload.
 * value begins at byte 3 (no padding). AF_UNIX SOCK_DGRAM preserves datagram
 * boundaries; the receiver derives element count from len / sizeof(element).
 */
typedef struct {
    uint8_t  type;
    uint16_t len;
    uint8_t  value[];
} __attribute__((__packed__)) lq_tlv_t;

/*
 * Send one link-quality event over the datagram socket.
 *   msg_type   - LQ_IPC_MSG_*
 *   entries    - pointer to count * entry_size bytes (stats_arg_t array, MAC str, ...)
 *   count      - number of entries (0 for payload-less messages)
 *   entry_size - sizeof one entry
 * Returns 0 on success, -1 on error (non-fatal: logged and ignored by caller).
 */
int lq_ipc_send(uint32_t msg_type, const void *entries,
                uint32_t count, size_t entry_size);

#ifdef __cplusplus
}
#endif
#endif /* LQ_IPC_SENDER_H */
