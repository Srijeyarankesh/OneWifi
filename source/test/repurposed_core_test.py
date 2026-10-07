#!/usr/bin/env python3
"""Execute real companion derivation/transaction functions using HAL types and mocked I/O."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HAL = ROOT.parent / "rdkb-halif-wifi/include"


def extract(name, path="source/core/wifi_ctrl_webconfig.c"):
    text = (ROOT / path).read_text()
    match = re.search(r"^[^\n]*\b" + name + r"\([^;]+?\)\n\{", text, re.M)
    if match is None:
        raise AssertionError(name)
    return text[match.start():text.index("\n}", match.end()) + 2] + "\n"


PRELUDE = r"""
#define _GNU_SOURCE
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
#include "cJSON.h"
#ifndef RETURN_OK
#define RETURN_OK 0
#define RETURN_ERR -1
#endif
#define WIFI_CTRL 0
#define wifi_util_error_print(...) ((void)0)
#define VAP_INDEX(cap, i) ((cap).wifi_prop.interface_map[i].index)
#define vap_svc_type_private 0
#define webconfig_error_none 0
#define webconfig_error_invalid_subdoc -2
typedef int webconfig_error_t;
typedef struct { unsigned int vap_index; bool exists; bool force_apply; void *acl_map; } rdk_wifi_vap_info_t;
typedef struct { wifi_vap_info_map_t vap_map; rdk_wifi_vap_info_t rdk_vap_array[MAX_NUM_VAP_PER_RADIO]; } rdk_wifi_vap_map_t;
typedef struct { wifi_radio_operationParam_t oper; rdk_wifi_vap_map_t vaps; } rdk_wifi_radio_t;
typedef struct { int unused; } wifi_global_config_t;
typedef struct { bool repurposed_vap_enable; } wifi_rfc_dml_parameters_t;
typedef struct { wifi_global_config_t config; wifi_hal_capability_t hal_cap; rdk_wifi_radio_t radios[MAX_NUM_RADIOS]; unsigned int num_radios; } webconfig_subdoc_decoded_data_t;
typedef struct { unsigned int descriptor; struct { webconfig_subdoc_decoded_data_t decoded; struct {char *raw;} encoded; } u; } webconfig_subdoc_data_t;
typedef struct { bool ctrl_initialized; int webconfig; } wifi_ctrl_t;
typedef struct { rdk_wifi_radio_t radio_config[MAX_NUM_RADIOS]; wifi_hal_capability_t hal_cap; wifi_global_config_t global_config; wifi_rfc_dml_parameters_t rfc_dml_parameters; } wifi_mgr_t;
typedef struct { struct {
    int (*init_vap_config_default_fn)(unsigned int,wifi_vap_info_t *,rdk_wifi_vap_info_t *);
    int (*update_rfc_config_fn)(unsigned int,wifi_rfc_dml_parameters_t *);
} desc; } wifi_db_t;
typedef struct vap_svc { int (*update_fn)(struct vap_svc *,unsigned int,wifi_vap_info_map_t *,rdk_wifi_vap_info_t *); } vap_svc_t;
static wifi_mgr_t mgr;
static wifi_db_t db;
static vap_svc_t service;
static wifi_ctrl_t ctrl;
static bool json_present,json_enable;
static int primary_calls,donor_calls,db_calls,status_calls,status_value;
static int fail_primary_at,fail_donor_at,fail_donor_all,fail_db,fail_status,default_fail;
static char order[128];
static size_t order_len;
static unsigned int physical_ids[4]={0,1,2,17};

wifi_mgr_t *get_wifimgr_obj(void) {return &mgr;}
wifi_db_t *get_wifidb_obj(void) {return &db;}
wifi_rfc_dml_parameters_t *get_wifi_db_rfc_parameters(void) {return &mgr.rfc_dml_parameters;}
unsigned int getNumberRadios(void) {return 3;}
unsigned int getTotalNumberVAPs(void) {return 4;}
bool isVapRepurposeTarget(unsigned int index) {return index==17;}
bool is_vap_private(wifi_platform_property_t *prop,unsigned int index) {(void)prop;return index<3;}
wifi_vap_info_t *get_wifidb_vap_parameters(unsigned int index) {
    for(unsigned int r=0;r<3;r++) for(unsigned int j=0;j<mgr.radio_config[r].vaps.vap_map.num_vaps;j++)
        if(mgr.radio_config[r].vaps.vap_map.vap_array[j].vap_index==index)
            return &mgr.radio_config[r].vaps.vap_map.vap_array[j];
    return NULL;
}
rdk_wifi_vap_info_t *get_wifidb_rdk_vap_info(unsigned int index) {
    for(unsigned int r=0;r<3;r++) for(unsigned int j=0;j<mgr.radio_config[r].vaps.vap_map.num_vaps;j++)
        if(mgr.radio_config[r].vaps.vap_map.vap_array[j].vap_index==index)
            return &mgr.radio_config[r].vaps.rdk_vap_array[j];
    return NULL;
}
int init_defaults(unsigned int index,wifi_vap_info_t *vap,rdk_wifi_vap_info_t *rdk) {
    if(default_fail)return -1;
    memset(vap,0,sizeof(*vap));vap->vap_index=index;vap->radio_index=0;vap->vap_mode=wifi_vap_mode_ap;
    strcpy(vap->vap_name,"hotspot_secure_2g");strcpy(vap->bridge_name,"brlan4");
    vap->u.bss_info.security.mode=wifi_security_mode_wpa2_enterprise;
    rdk->vap_index=index;rdk->exists=true;return 0;
}
int write_rfc(unsigned int index,wifi_rfc_dml_parameters_t *rfc) {
    (void)index;db_calls++;order[order_len++]='R';
    if(fail_db)return -1;
    mgr.rfc_dml_parameters=*rfc;return 0;
}
int mock_donor_apply(vap_svc_t *svc,unsigned int radio,wifi_vap_info_map_t *map,rdk_wifi_vap_info_t *rdk) {
    (void)svc;(void)radio;donor_calls++;order[order_len++]='D';assert(map->num_vaps==1);
    assert(!rdk->force_apply);
    if(donor_calls==fail_donor_at || fail_donor_all)return -1;
    *get_wifidb_vap_parameters(17)=map->vap_array[0];*get_wifidb_rdk_vap_info(17)=*rdk;return 0;
}
vap_svc_t *get_svc_by_type(wifi_ctrl_t *c,int type) {(void)c;(void)type;return &service;}
int webconfig_hal_private_vap_apply(wifi_ctrl_t *c,webconfig_subdoc_decoded_data_t *data) {
    (void)c;primary_calls++;order[order_len++]='P';
    for(unsigned int r=0;r<3;r++) {
        mgr.radio_config[r].vaps.vap_map.vap_array[0]=data->radios[r].vaps.vap_map.vap_array[0];
        if(primary_calls==fail_primary_at)return -1;
    }
    return 0;
}
int publish_repurposed_vap_status(bool enable) {
    status_calls++;status_value=enable;order[order_len++]='S';
    return fail_status?-1:0;
}
bool is_vap_param_config_changed(wifi_vap_info_t *old,wifi_vap_info_t *new,
    rdk_wifi_vap_info_t *old_rdk,rdk_wifi_vap_info_t *new_rdk,bool sta) {
    (void)sta;return memcmp(old,new,sizeof(*old))!=0 || old_rdk->exists!=new_rdk->exists;
}
int update_repurposed_vap_acl(unsigned int index,bool active) {
    (void)active;assert(index==17);return 0;
}
int encode_private_subdoc(int *config,webconfig_subdoc_data_t *data) {
    (void)config;data->u.encoded.raw=strdup("{}");return data->u.encoded.raw?0:-1;
}
void webconfig_data_free(webconfig_subdoc_data_t *data) {
    free(data->u.encoded.raw);data->u.encoded.raw=NULL;
}
int webconfig_decode(int *config,webconfig_subdoc_data_t *data,const char *raw);

"""

MAIN = r"""
int webconfig_decode(int *config,webconfig_subdoc_data_t *data,const char *raw) {
    (void)config;
    webconfig_init_subdoc_data(data);
    data->u.encoded.raw=strdup(raw);
    return apply_private_repurposed_request(&ctrl,data);
}
static void reset_fixture(void) {
    memset(&mgr,0,sizeof(mgr));memset(order,0,sizeof(order));order_len=0;
    primary_calls=donor_calls=db_calls=status_calls=status_value=0;
    fail_primary_at=fail_donor_at=fail_donor_all=fail_db=fail_status=default_fail=0;
    json_present=true;json_enable=true;
    db.desc.init_vap_config_default_fn=init_defaults;db.desc.update_rfc_config_fn=write_rfc;
    service.update_fn=mock_donor_apply;ctrl.ctrl_initialized=true;
    for(unsigned int i=0;i<4;i++)mgr.hal_cap.wifi_prop.interface_map[i].index=physical_ids[i];
    for(unsigned int r=0;r<3;r++) {
        wifi_vap_info_t *vap=&mgr.radio_config[r].vaps.vap_map.vap_array[0];
        mgr.radio_config[r].oper.band=r==0?WIFI_FREQUENCY_2_4_BAND:r==1?WIFI_FREQUENCY_5_BAND:WIFI_FREQUENCY_6_BAND;
        mgr.radio_config[r].vaps.vap_map.num_vaps=r==0?2:1;
        vap->vap_index=r;vap->radio_index=r;vap->vap_mode=wifi_vap_mode_ap;
        snprintf(vap->vap_name,sizeof(vap->vap_name),"private_ssid_%ug",r==0?2:r==1?5:6);
        snprintf(vap->u.bss_info.ssid,sizeof(vap->u.bss_info.ssid),"source-%u",r);
        snprintf(vap->u.bss_info.security.u.key.key,sizeof(vap->u.bss_info.security.u.key.key),"password-%u",r);
        strcpy(vap->bridge_name,"brlan0");vap->u.bss_info.bssid[5]=r+1;
        vap->u.bss_info.enabled=true;vap->u.bss_info.bssMaxSta=31+r;
        vap->u.bss_info.security.mode=r==2?wifi_security_mode_wpa3_personal:wifi_security_mode_wpa2_personal;
        vap->u.bss_info.security.rekey_interval=700+r;
        vap->u.bss_info.security.encr=wifi_encryption_aes;
        vap->u.bss_info.wps.enable=true;vap->u.bss_info.wpsPushButton=1;
        vap->u.bss_info.mld_info.common_info.mld_enable=true;
        vap->u.bss_info.mld_info.common_info.mld_id=4;
        vap->u.bss_info.interworking.interworking.interworkingEnabled=true;
        vap->u.bss_info.interworking.passpoint.enable=true;
        mgr.radio_config[r].vaps.rdk_vap_array[0].vap_index=r;
        mgr.radio_config[r].vaps.rdk_vap_array[0].exists=true;
    }
    wifi_vap_info_t *donor=&mgr.radio_config[0].vaps.vap_map.vap_array[1];
    init_defaults(17,donor,&mgr.radio_config[0].vaps.rdk_vap_array[1]);
    donor->u.bss_info.bssid[5]=0x99;
}
static void prepare(webconfig_subdoc_data_t *data) {
    webconfig_init_subdoc_data(data);
    data->u.encoded.raw=json_present ?
        (json_enable ? "{\"RepurposedVapConfig\":[{\"Enabled\":true}]}" :
                       "{\"RepurposedVapConfig\":[{\"Enabled\":false}]}") : "{}";
}
static void assert_dormant(void) {
    wifi_vap_info_t *vap=get_wifidb_vap_parameters(17);
    assert(!vap->u.bss_info.enabled && vap->repurposed_vap_name[0]==0);
}
int main(void) {
    webconfig_subdoc_data_t *request=calloc(1,sizeof(*request));
    wifi_vap_info_t *derived=calloc(1,sizeof(*derived));
    rdk_wifi_vap_info_t rdk;
    assert(request&&derived);
    reset_fixture();prepare(request);
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.enabled=false;
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)==0);
    assert(derived->vap_index==17 && derived->radio_index==0 && strcmp(derived->vap_name,"hotspot_secure_2g")==0);
    assert(derived->u.bss_info.bssid[5]==0x99 && strcmp(derived->bridge_name,"brlan0")==0);
    assert(strcmp(derived->u.bss_info.ssid,"source-0")==0 && derived->u.bss_info.bssMaxSta==31);
    assert(derived->u.bss_info.security.rekey_interval==700);
    assert(strcmp(derived->u.bss_info.security.u.key.key,"password-0")==0);
    assert(derived->u.bss_info.security.mode==wifi_security_mode_wpa3_compatibility);
    assert(!derived->u.bss_info.wps.enable && !derived->u.bss_info.wpsPushButton);
    assert(!derived->u.bss_info.mld_info.common_info.mld_enable);
    assert(!derived->u.bss_info.interworking.interworking.interworkingEnabled);
    assert(!derived->u.bss_info.interworking.passpoint.enable);
    assert(!derived->u.bss_info.enabled);
    puts("PASS derivation preserves 2G settings and donor identity; PCM/WPS/MLO policy");
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.mode=wifi_security_mode_none;
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)==0);
    assert(strcmp(derived->u.bss_info.security.u.key.key,"password-1")==0);
    assert(strcmp(derived->u.bss_info.ssid,"source-0")==0 && derived->u.bss_info.bssMaxSta==31);
    request->u.decoded.radios[1].vaps.vap_map.vap_array[0].u.bss_info.security.mode=wifi_security_mode_none;
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)==0);
    assert(strcmp(derived->u.bss_info.security.u.key.key,"password-2")==0);
    request->u.decoded.radios[2].vaps.vap_map.vap_array[0].u.bss_info.security.mode=wifi_security_mode_none;
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)!=0);
    puts("PASS password-only 5G/6G fallback and no usable credential rejection");
    prepare(request);
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.mode=wifi_security_mode_none;
    strcpy(request->u.decoded.radios[1].vaps.vap_map.vap_array[0].u.bss_info.security.u.key.key,"bad");
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)!=0);
    prepare(request);
    memset(request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.u.key.key,'a',
        sizeof(request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.u.key.key));
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)!=0);
    puts("PASS invalid secured-5G key is rejected and nonterminated/raw-length PSK rejected");


    reset_fixture();prepare(request);
    strcpy(request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.u.key.key,"short");
    assert(apply_private_repurposed_request(&ctrl,request)!=0);
    assert(primary_calls==0 && donor_calls==0 && db_calls==0 && status_calls==0);
    puts("PASS invalid key rejected before native configuration writes");

    reset_fixture();prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(mgr.rfc_dml_parameters.repurposed_vap_enable && status_value==1 && status_calls==1);
    assert(strcmp(order,"PDRS")==0);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.mode==wifi_security_mode_wpa3_transition);
    assert(get_wifidb_vap_parameters(1)->u.bss_info.security.mode==wifi_security_mode_wpa3_transition);
    assert(get_wifidb_vap_parameters(2)->u.bss_info.security.mode==wifi_security_mode_wpa3_personal);
    prepare(request);
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.mode=wifi_security_mode_wpa2_personal;
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.mode==wifi_security_mode_wpa2_personal);
    int before=primary_calls;
    assert(webconfig_reapply_repurposed_vap(&ctrl)==0);
    assert(primary_calls==before && get_wifidb_vap_parameters(0)->u.bss_info.security.mode==wifi_security_mode_wpa2_personal);
    json_enable=false;prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(!mgr.rfc_dml_parameters.repurposed_vap_enable && status_value==0);
    assert_dormant();
    puts("PASS rising-edge-only migration, override/reboot preservation and dormant disable");

    reset_fixture();prepare(request);fail_donor_at=1;
    assert(apply_private_repurposed_request(&ctrl,request)!=0);
    assert(primary_calls==2 && donor_calls==2 && db_calls==0 && status_calls==0);
    assert(!mgr.rfc_dml_parameters.repurposed_vap_enable);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.mode==wifi_security_mode_wpa2_personal);
    assert_dormant();
    puts("PASS companion HAL failure restores native configuration and dormant target");

    reset_fixture();prepare(request);fail_primary_at=1;
    assert(apply_private_repurposed_request(&ctrl,request)!=0);
    assert(primary_calls==2 && donor_calls==1 && db_calls==0 && status_calls==0);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.mode==wifi_security_mode_wpa2_personal);
    assert_dormant();
    puts("PASS native apply failure rolls back before RFC commit");

    reset_fixture();prepare(request);fail_db=1;
    assert(apply_private_repurposed_request(&ctrl,request)!=0);
    assert(primary_calls==2 && donor_calls==2 && db_calls==1 && status_calls==0);
    assert(!mgr.rfc_dml_parameters.repurposed_vap_enable);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.mode==wifi_security_mode_wpa2_personal);
    assert_dormant();
    puts("PASS RFC persistence failure restores old settings and does not publish success");

    reset_fixture();json_present=false;prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(primary_calls==1 && donor_calls==0 && db_calls==0 && status_calls==0);
    reset_fixture();prepare(request);fail_status=1;
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(mgr.rfc_dml_parameters.repurposed_vap_enable);
    puts("PASS legacy request path unchanged and notification failure does not undo applied config");

    reset_fixture();mgr.rfc_dml_parameters.repurposed_vap_enable=true;fail_donor_at=1;
    assert(webconfig_reapply_repurposed_vap(&ctrl)!=0);
    assert(primary_calls==0 && donor_calls==2 && status_calls==0);
    assert_dormant();
    puts("PASS boot reconstruction failure falls back to dormant without primary migration");
    reset_fixture();
    assert(webconfig_set_repurposed_vap(&ctrl,true)==0);
    assert(mgr.rfc_dml_parameters.repurposed_vap_enable && status_value==1);
    assert(webconfig_set_repurposed_vap(&ctrl,false)==0);
    assert(!mgr.rfc_dml_parameters.repurposed_vap_enable && status_value==0);
    assert_dormant();
    puts("PASS RFC setter emits real JSON metadata into the shared private apply path");
    reset_fixture();prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    int notified=status_calls,created=donor_calls;
    json_present=false;prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(donor_calls==created && status_calls==notified);
    prepare(request);
    strcpy(request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.ssid,"updated-2g");
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(strcmp(get_wifidb_vap_parameters(17)->u.bss_info.ssid,"updated-2g")==0);
    assert(status_calls==notified && mgr.rfc_dml_parameters.repurposed_vap_enable);
    puts("PASS active metadata-absent update reconciles source and identical update skips donor HAL");

    json_present=true;json_enable=false;prepare(request);fail_db=1;
    assert(apply_private_repurposed_request(&ctrl,request)!=0);
    assert(mgr.rfc_dml_parameters.repurposed_vap_enable && status_calls==notified);
    assert(strcmp(get_wifidb_vap_parameters(17)->repurposed_vap_name,WIFI_REPURPOSED_PRIVATE_2G_NAME)==0);
    fail_db=0;prepare(request);
    for(unsigned int r=0;r<3;r++)
        request->u.decoded.radios[r].vaps.vap_map.vap_array[0].u.bss_info.security.mode=wifi_security_mode_none;
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(!mgr.rfc_dml_parameters.repurposed_vap_enable);
    assert_dormant();
    puts("PASS failed disable restores active donor; explicit disable accepts open private sources");

    reset_fixture();prepare(request);
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.encr=wifi_encryption_aes_gcmp256;
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)==0);
#ifdef CONFIG_IEEE80211BE
    assert(derived->u.bss_info.security.encr==wifi_encryption_aes_gcmp256);
#else
    assert(derived->u.bss_info.security.encr==wifi_encryption_aes);
#endif
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.mode=wifi_security_mode_none;
    assert(derive_repurposed_vap_config(&request->u.decoded,17,derived,&rdk)==0);
    assert(derived->u.bss_info.security.encr==wifi_encryption_aes);
    puts("PASS companion preserves supported 2G AES/GCMP cipher and defaults open source to AES");

    prepare(request);
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.encr=wifi_encryption_aes_gcmp256;
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.wpa3_transition_disable=true;
    request->u.decoded.radios[1].vaps.vap_map.vap_array[0].u.bss_info.security.encr=wifi_encryption_aes_tkip;
    request->u.decoded.radios[1].vaps.vap_map.vap_array[0].u.bss_info.security.wpa3_transition_disable=true;
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(!get_wifidb_vap_parameters(0)->u.bss_info.security.wpa3_transition_disable);
    assert(!get_wifidb_vap_parameters(1)->u.bss_info.security.wpa3_transition_disable);
#ifdef CONFIG_IEEE80211BE
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.encr==wifi_encryption_aes_gcmp256);
#else
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.encr==wifi_encryption_aes);
#endif
    assert(get_wifidb_vap_parameters(1)->u.bss_info.security.encr==wifi_encryption_aes);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.rekey_interval==700);
    prepare(request);
    request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.security.wpa3_transition_disable=true;
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.wpa3_transition_disable);
    assert(webconfig_reapply_repurposed_vap(&ctrl)==0);
    assert(get_wifidb_vap_parameters(0)->u.bss_info.security.wpa3_transition_disable);
    assert(!get_wifidb_vap_parameters(17)->u.bss_info.security.wpa3_transition_disable);
    puts("PASS rising-edge migration clears transition-disable, preserves supported cipher and retains later overrides");
    reset_fixture();prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(!get_wifidb_rdk_vap_info(17)->force_apply);
    prepare(request);
    strcpy(request->u.decoded.radios[0].vaps.vap_map.vap_array[0].u.bss_info.ssid,"failed-update");
    fail_donor_all=1;int successful_notifications=status_calls;
    assert(apply_private_repurposed_request(&ctrl,request)!=0);
    assert(get_wifidb_rdk_vap_info(17)->force_apply);
    assert(strcmp(get_wifidb_vap_parameters(0)->u.bss_info.ssid,"source-0")==0);
    assert(strcmp(get_wifidb_vap_parameters(17)->u.bss_info.ssid,"source-0")==0);
    assert(status_calls==successful_notifications);
    int failed_attempts=donor_calls;
    fail_donor_all=0;prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(donor_calls==failed_attempts+1 && !get_wifidb_rdk_vap_info(17)->force_apply);
    assert(status_calls==successful_notifications+1);
    prepare(request);
    assert(apply_private_repurposed_request(&ctrl,request)==0);
    assert(donor_calls==failed_attempts+1);
    puts("PASS persistent apply/recovery failures force identical retry through HAL; success alone clears retry hint");
    free(request);free(derived);return 0;
}
"""

FUNCTIONS = [
    "webconfig_init_subdoc_data", "repurposed_vap_index", "get_repurposed_vap_dormant_config",
    "repurposed_private_source", "repurposed_personal_security", "derive_repurposed_vap_config",
    "apply_repurposed_vap_config", "webconfig_reapply_repurposed_vap", "apply_private_repurposed_request",
    "webconfig_set_repurposed_vap",
]


def main():
    source = PRELUDE + extract("decode_repurposed_vap_config", "source/webconfig/wifi_webconfig_private.c") + "".join(extract(name) for name in FUNCTIONS) + MAIN
    with tempfile.TemporaryDirectory(prefix=".core-test-", dir=ROOT) as directory:
        binary = str(Path(directory) / "core_test")
        for ieee80211be in (False, True):
            args = ["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                    "-DWIFI_HAL_VERSION_3", "-I" + str(HAL), "-I" + str(ROOT / "tests/deps"),
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-x", "c", "-", str(ROOT / "tests/deps/cJSON.c"), "-o", binary]
            if ieee80211be:
                args.append("-DCONFIG_IEEE80211BE")
            print("CONFIG_IEEE80211BE =", ieee80211be, flush=True)
            subprocess.run(args, input=source, text=True, check=True)
            subprocess.run([binary], check=True)


if __name__ == "__main__":
    main()
