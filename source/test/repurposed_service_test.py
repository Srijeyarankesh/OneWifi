#!/usr/bin/env python3
"""Check real private-service ordering with actual HAL structures and failure injection."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HAL = ROOT.parent / "rdkb-halif-wifi/include"

PRELUDE = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <wifi_hal.h>
#ifndef RETURN_OK
#define RETURN_OK 0
#define RETURN_ERR -1
#endif
#define WIFI_CTRL 0
#define wifi_util_error_print(...) ((void)0)
#define wifi_util_info_print(...) ((void)0)
typedef struct { bool exists; } rdk_wifi_vap_info_t;
typedef struct { int unused; } vap_svc_t;
typedef struct { struct {
    int (*print_fn)(const char *,...);
    int (*update_wifi_vap_info_fn)(char *,wifi_vap_info_t *,rdk_wifi_vap_info_t *);
    int (*update_wifi_interworking_cfg_fn)(char *,wifi_interworking_t *);
    int (*update_wifi_security_config_fn)(char *,wifi_vap_security_t *);
} desc; } wifi_db_t;
static wifi_db_t db;
static char order[64];
static unsigned int order_len;
static int hal_calls,cache_calls,db_calls,fail_hal_at,fail_acl,fail_cache,fail_db_at;
static bool acl_ready,last_acl_active;
static wifi_vap_info_t cached;
bool isVapRepurposeTarget(unsigned int index) { return index==17; }
bool isVapLnfPsk(unsigned int index) { (void)index;return false; }
int configure_lnf_psk_radius_from_hotspot(wifi_vap_info_t *vap) {(void)vap;return 0;}
wifi_db_t *get_wifidb_obj(void) {return &db;}
wifi_vap_info_t *get_wifidb_vap_parameters(unsigned int index) {(void)index;return &cached;}
unsigned long long get_current_ms_time(void) {return 0;}
char *getVAPName(unsigned int index) {(void)index;return "private_ssid_2g";}
int update_vap_hal_prop_bridge_name(vap_svc_t *svc,wifi_vap_info_map_t *map) {(void)svc;(void)map;return 0;}
int quiet_print(const char *format,...) {(void)format;return 0;}
int wifi_hal_createVAP(unsigned int radio,wifi_vap_info_map_t *map) {
    (void)radio;hal_calls++;
    bool up=map->vap_array[0].u.bss_info.enabled;
    order[order_len++]=up?'U':'D';
    if(map->vap_array[0].vap_index==17) {
        assert(!map->vap_array[0].u.bss_info.wps.enable);
        assert(!map->vap_array[0].u.bss_info.wpsPushButton);
        if(up)assert(acl_ready);
    }
    return hal_calls==fail_hal_at?-1:0;
}
int update_repurposed_vap_acl(unsigned int index,bool active) {
    assert(index==17);order[order_len++]='A';last_acl_active=active;
    if(fail_acl)return -1;
    acl_ready=true;return 0;
}
int update_global_cache(wifi_vap_info_map_t *map,rdk_wifi_vap_info_t *rdk) {
    (void)rdk;cache_calls++;order[order_len++]='C';
    if(fail_cache)return -1;
    cached=map->vap_array[0];return 0;
}
int persist_vap(char *name,wifi_vap_info_t *vap,rdk_wifi_vap_info_t *rdk) {
    (void)name;(void)vap;(void)rdk;db_calls++;order[order_len++]='P';return db_calls==fail_db_at?-1:0;
}
int persist_interworking(char *name,wifi_interworking_t *config) {
    (void)name;(void)config;db_calls++;order[order_len++]='I';return db_calls==fail_db_at?-1:0;
}
int persist_security(char *name,wifi_vap_security_t *config) {
    (void)name;(void)config;db_calls++;order[order_len++]='S';return db_calls==fail_db_at?-1:0;
}
"""

MAIN = r"""
static void reset_fixture(wifi_vap_info_map_t *map,rdk_wifi_vap_info_t *rdk) {
    memset(map,0,sizeof(*map));memset(&cached,0,sizeof(cached));memset(order,0,sizeof(order));
    order_len=0;hal_calls=cache_calls=db_calls=fail_hal_at=fail_acl=fail_cache=fail_db_at=0;
    acl_ready=last_acl_active=false;rdk->exists=true;map->num_vaps=1;
    map->vap_array[0].vap_index=17;map->vap_array[0].u.bss_info.enabled=true;
    map->vap_array[0].u.bss_info.wps.enable=true;map->vap_array[0].u.bss_info.wpsPushButton=1;
    strcpy(map->vap_array[0].repurposed_vap_name,WIFI_REPURPOSED_PRIVATE_2G_NAME);
    db.desc.print_fn=quiet_print;db.desc.update_wifi_vap_info_fn=persist_vap;
    db.desc.update_wifi_interworking_cfg_fn=persist_interworking;
    db.desc.update_wifi_security_config_fn=persist_security;
}
int main(void) {
    wifi_vap_info_map_t *map=calloc(1,sizeof(*map));rdk_wifi_vap_info_t rdk;vap_svc_t svc={0};assert(map);
    reset_fixture(map,&rdk);
    assert(vap_svc_private_update(&svc,0,map,&rdk)==0);
    assert(strcmp(order,"DAUC")==0 && cached.u.bss_info.enabled && db_calls==0 && last_acl_active);
    puts("PASS disabled preparation -> ACL -> enabled HAL -> runtime cache; no donor persistence");
    reset_fixture(map,&rdk);map->vap_array[0].u.bss_info.enabled=false;
    assert(vap_svc_private_update(&svc,0,map,&rdk)==0);
    assert(strcmp(order,"DAC")==0 && !cached.u.bss_info.enabled && last_acl_active);
    reset_fixture(map,&rdk);map->vap_array[0].u.bss_info.enabled=false;
    map->vap_array[0].repurposed_vap_name[0]=0;
    assert(vap_svc_private_update(&svc,0,map,&rdk)==0);
    assert(strcmp(order,"DAC")==0 && !cached.u.bss_info.enabled && !last_acl_active);
    puts("PASS administratively disabled and dormant target never enable");

    reset_fixture(map,&rdk);fail_hal_at=1;
    assert(vap_svc_private_update(&svc,0,map,&rdk)!=0);
    assert(strcmp(order,"DD")==0 && cache_calls==0 && db_calls==0);
    reset_fixture(map,&rdk);fail_acl=1;
    assert(vap_svc_private_update(&svc,0,map,&rdk)!=0);
    assert(strcmp(order,"DAD")==0 && cache_calls==0 && db_calls==0);
    reset_fixture(map,&rdk);fail_hal_at=2;
    assert(vap_svc_private_update(&svc,0,map,&rdk)!=0);
    assert(strcmp(order,"DAUD")==0 && cache_calls==0 && db_calls==0);
    reset_fixture(map,&rdk);fail_cache=1;
    assert(vap_svc_private_update(&svc,0,map,&rdk)!=0);
    assert(strcmp(order,"DAUCD")==0 && !cached.u.bss_info.enabled && db_calls==0);
    puts("PASS preparation/ACL/activation/cache failures disable target and propagate error");

    reset_fixture(map,&rdk);map->vap_array[0].repurposed_vap_name[0]=0;
    assert(vap_svc_private_update(&svc,0,map,&rdk)!=0 && hal_calls==0);
    reset_fixture(map,&rdk);map->vap_array[0].u.bss_info.enabled=false;
    strcpy(map->vap_array[0].repurposed_vap_name,"unrelated_repurpose");
    assert(vap_svc_private_update(&svc,0,map,&rdk)!=0 && hal_calls==0);
    puts("PASS unmarked enabled and unrelated-role donor writes rejected before HAL");

    reset_fixture(map,&rdk);map->vap_array[0].vap_index=0;
    assert(vap_svc_private_update(&svc,0,map,&rdk)==0);
    assert(strcmp(order,"UPIS")==0 && cache_calls==0 && db_calls==3);
    for(int failure=1;failure<=3;failure++) {
        reset_fixture(map,&rdk);map->vap_array[0].vap_index=0;fail_db_at=failure;
        assert(vap_svc_private_update(&svc,0,map,&rdk)!=0 && db_calls==failure);
    }
    puts("PASS native private keeps normal HAL sequence and propagates each persistence failure");
    free(map);return 0;
}
"""


def main():
    text = (ROOT / "source/core/services/vap_svc_private.c").read_text()
    match = re.search(r"^int vap_svc_private_update\([^;]+?\)\n\{", text, re.M)
    if match is None:
        raise AssertionError("vap_svc_private_update")
    function = text[match.start():text.index("\n}", match.end()) + 2]
    with tempfile.TemporaryDirectory(prefix=".service-test-", dir=ROOT) as directory:
        binary = str(Path(directory) / "service_test")
        subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                        "-DWIFI_HAL_VERSION_3", "-I" + str(HAL),
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-x", "c", "-", "-o", binary],
                       input=PRELUDE + function + MAIN, text=True, check=True)
        subprocess.run([binary], check=True)


if __name__ == "__main__":
    main()
