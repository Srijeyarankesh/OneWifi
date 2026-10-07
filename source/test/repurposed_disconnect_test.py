#!/usr/bin/env python3
"""Exercise actual queued disconnect cleanup after the donor's runtime role is cleared."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRELUDE = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#define RETURN_OK 0
#define RETURN_ERR -1
#define FALSE false
#define MAX_NUM_RADIOS 3
#define WIFI_CTRL 0
#define client_state_disconnected 0
#define ctrl_webconfig_state_associated_clients_cfg_rsp_pending 1
#define wifi_util_error_print(...) ((void)0)
#define wifi_util_dbg_print(...) ((void)0)
#define wifi_util_info_print(...) ((void)0)
typedef bool BOOL;
typedef unsigned long ULONG;
typedef unsigned char mac_address_t[6];
typedef char mac_addr_str_t[18];
typedef struct {
    unsigned int ap_index;
    struct { bool cli_MLDEnable,cli_Active;int cli_RSSI;mac_address_t cli_MACAddress; } dev_stats;
    bool association_link;
    struct {bool cli_MLDSta;struct {int cli_RSSI;} cli_LinkInfo[MAX_NUM_RADIOS];} mld_info;
    int client_state;
} assoc_dev_data_t;
typedef struct {assoc_dev_data_t *entry;} hash_map_t;
typedef struct {unsigned int vap_index;hash_map_t *associated_devices_map,*associated_devices_diff_map;pthread_mutex_t *associated_devices_lock;} rdk_wifi_vap_info_t;
typedef struct {int webconfig_state;} wifi_ctrl_t;
typedef struct {wifi_ctrl_t ctrl;} wifi_mgr_t;
typedef struct {char phyAddr[18];bool Status,mld_sta;} LM_host_t;
typedef struct {LM_host_t host[1];} LM_wifi_hosts_t;
static wifi_mgr_t mgr;
static rdk_wifi_vap_info_t vap;
static hash_map_t associated;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static int lm_calls,hotspot_calls,count_calls;
static bool role_active;
static ULONG final_count,initial_count;
wifi_mgr_t *get_wifimgr_obj(void) {return &mgr;}
rdk_wifi_vap_info_t *get_wifidb_rdk_vap_info(unsigned int index) {return index==vap.vap_index?&vap:NULL;}
bool isVapRepurposeTarget(unsigned int index) {return index==17;}
bool isVapPrivateNetwork(unsigned int index) {return index==0 || (index==17 && role_active);}
bool isVapXhs(unsigned int index) {(void)index;return false;}
bool vap_svc_is_public(unsigned int index) {return index==9;}
void update_lm_wifi_host_SSID_DM_ref(LM_host_t *host,assoc_dev_data_t *dev,unsigned int index) {(void)host;(void)dev;assert(index==vap.vap_index);}
void update_lm_wifi_host_RSSI(LM_host_t *host,assoc_dev_data_t *dev) {(void)host;assert(dev->dev_stats.cli_RSSI==0);}
void to_mac_str(mac_address_t mac,mac_addr_str_t str) {snprintf(str,18,"%02x:%02x:%02x:%02x:%02x:%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);}
void str_tolower(char *value) {(void)value;}
int notify_hotspot(wifi_ctrl_t *ctrl,assoc_dev_data_t *dev) {(void)ctrl;(void)dev;hotspot_calls++;return 0;}
int notify_LM_Lite(wifi_ctrl_t *ctrl,LM_wifi_hosts_t *hosts,bool single) {(void)ctrl;assert(single && !hosts->host[0].Status);lm_calls++;return 0;}
int notify_associated_entries(wifi_ctrl_t *ctrl,unsigned int index,ULONG newer,ULONG older) {(void)ctrl;assert(index==vap.vap_index);count_calls++;final_count=newer;initial_count=older;return 0;}
ULONG hash_map_count(hash_map_t *map) {return map->entry?1:0;}
assoc_dev_data_t *hash_map_get_first(hash_map_t *map) {return map->entry;}
assoc_dev_data_t *hash_map_get_next(hash_map_t *map,assoc_dev_data_t *entry) {(void)map;(void)entry;return NULL;}
assoc_dev_data_t *hash_map_remove(hash_map_t *map,char *key) {(void)key;assoc_dev_data_t *entry=map->entry;map->entry=NULL;return entry;}
int add_client_diff_assoclist(hash_map_t **map,char *key,assoc_dev_data_t *dev) {(void)map;(void)key;(void)dev;return 0;}
void check_and_remove_mac_on_other_vaps(assoc_dev_data_t *dev) {(void)dev;assert(false);}
"""
MAIN = r"""
static void fixture(unsigned int index,assoc_dev_data_t *event) {
    memset(&mgr,0,sizeof(mgr));memset(&vap,0,sizeof(vap));memset(event,0,sizeof(*event));
    vap.vap_index=index;vap.associated_devices_map=&associated;vap.associated_devices_lock=&lock;
    event->ap_index=index;event->dev_stats.cli_MACAddress[5]=1;event->dev_stats.cli_Active=true;
    associated.entry=malloc(sizeof(*event));assert(associated.entry);*associated.entry=*event;
    lm_calls=hotspot_calls=count_calls=0;role_active=false;
}
int main(void) {
    assoc_dev_data_t event;
    fixture(17,&event);
    assert(!isVapPrivateNetwork(17));
    process_disassoc_device_event(&event);
    assert(associated.entry==NULL && lm_calls==1 && hotspot_calls==0);
    assert(count_calls==1 && initial_count==1 && final_count==0);
    assert(mgr.ctrl.webconfig_state & ctrl_webconfig_state_associated_clients_cfg_rsp_pending);
    process_disassoc_device_event(&event);
    assert(lm_calls==1 && count_calls==1);
    puts("PASS queued donor disconnect after role clear removes client and publishes LM/count cleanup once");
    fixture(0,&event);process_disassoc_device_event(&event);
    assert(lm_calls==1 && count_calls==1 && final_count==0 && hotspot_calls==0);
    fixture(9,&event);process_disassoc_device_event(&event);
    assert(lm_calls==0 && count_calls==0 && hotspot_calls==1);
    puts("PASS native private and public disconnect routes retain their existing behavior");
    return 0;
}
"""


def main():
    text = (ROOT / "source/core/wifi_ctrl_queue_handlers.c").read_text()
    functions = []
    for name in ["lm_notify_disassoc", "process_device_removal", "process_disassoc_device_event"]:
        match = re.search(r"^(?:int|void) " + name + r"\([^;]+?\)\n\{", text, re.M)
        if match is None:
            raise AssertionError(name)
        functions.append(text[match.start():text.index("\n}", match.end()) + 2] + "\n")
    with tempfile.TemporaryDirectory(prefix=".disconnect-test-", dir=ROOT) as directory:
        binary = str(Path(directory) / "disconnect_test")
        subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-pthread",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-x", "c", "-", "-o", binary],
                       input=PRELUDE + "".join(functions) + MAIN, text=True, check=True)
        subprocess.run([binary], check=True)


if __name__ == "__main__":
    main()
