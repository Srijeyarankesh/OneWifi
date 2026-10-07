#!/usr/bin/env python3
"""Host checks of the real runtime role and ACL functions, with HAL dependencies stubbed."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def extract(path, name):
    text = (ROOT / path).read_text()
    match = re.search(r"^(?:bool|int) " + name + r"\([^;]+?\)\n\{", text, re.M)
    if match is None:
        raise AssertionError(name)
    # Top-level C closing brace; preprocessing selects one of the ACL API branches.
    end = text.index("\n}", match.end()) + 2
    return text[match.start():end] + "\n"


PRELUDE = r"""
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#define RETURN_OK 0
#define RETURN_ERR -1
#define wifi_mac_filter_mode_black_list 0
#define WIFI_REPURPOSED_PRIVATE_2G_NAME "private_ssid_2g_compat"
typedef unsigned char mac_address_t[6];
typedef char mac_addr_str_t[18];
typedef struct entry { mac_address_t mac; struct entry *next; } acl_entry_t;
typedef struct { acl_entry_t *first; } hash_map_t;
typedef struct { char repurposed_vap_name[64]; union { struct {
    bool mac_filter_enable; int mac_filter_mode;
} bss_info; } u; } wifi_vap_info_t;
typedef struct { hash_map_t *acl_map; } rdk_wifi_vap_info_t;
typedef struct { struct { int wifi_prop; } hal_cap; } wifi_mgr_t;
wifi_mgr_t manager;
wifi_mgr_t *manager_ptr=&manager;
wifi_vap_info_t donor,source;
rdk_wifi_vap_info_t source_rdk;
int donor_index=17,source_index=3,clear_calls,add_calls,mode_calls,last_mode,fail_clear,fail_add,fail_mode;
wifi_mgr_t *get_wifimgr_obj(void) {return manager_ptr;}
int convert_vap_name_to_index(int *prop,const char *name) {(void)prop; return strcmp(name,"hotspot_secure_2g")==0 ? donor_index : source_index;}
wifi_vap_info_t *get_wifidb_vap_parameters(unsigned int idx) {return (int)idx==donor_index ? &donor : (int)idx==source_index ? &source : NULL;}
rdk_wifi_vap_info_t *get_wifidb_rdk_vap_info(unsigned int idx) {return (int)idx==source_index ? &source_rdk : NULL;}
bool isVapPrivate(unsigned int idx) {return (int)idx==source_index;}
bool isVapXhs(unsigned int idx) {return idx==5;}
bool isVapLnf(unsigned int idx) {return idx==6;}
bool isVapHotspot(unsigned int idx) {return (int)idx==donor_index || idx==9;}
acl_entry_t *hash_map_get_first(hash_map_t *map) {return map->first;}
acl_entry_t *hash_map_get_next(hash_map_t *map,acl_entry_t *entry) {(void)map;return entry->next;}
bool is_zero_mac(mac_address_t mac) {static unsigned char zero[6]; return memcmp(mac,zero,6)==0;}
void to_mac_str(mac_address_t mac,mac_addr_str_t str) {snprintf(str,18,"%02x:%02x:%02x:%02x:%02x:%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);}
int wifi_hal_delApAclDevices(unsigned int idx) {assert((int)idx==donor_index);clear_calls++;return fail_clear?-1:0;}
int wifi_hal_addApAclDevice(unsigned int idx,char *mac) {assert((int)idx==donor_index);assert(mac[0]);add_calls++;return fail_add?-1:0;}
int wifi_hal_setApMacAddressControlMode(unsigned int idx,int mode) {assert((int)idx==donor_index);mode_calls++;last_mode=mode;return fail_mode?-1:0;}
#define wifi_delApAclDevices wifi_hal_delApAclDevices
#define wifi_addApAclDevice wifi_hal_addApAclDevice
#define wifi_setApMacAddressControlMode wifi_hal_setApMacAddressControlMode
bool isVapRepurposeTarget(unsigned int);
bool isVapRepurposed(unsigned int);
bool isVapPrivateNetwork(unsigned int);
"""

MAIN = r"""
int main(void) {
    acl_entry_t second={{2,3,4,5,6,7},NULL};
    acl_entry_t first={{1,2,3,4,5,6},&second};
    hash_map_t map={&first};
    source_rdk.acl_map=&map;
    assert(isVapPrivateNetwork(source_index));
    assert(isVapRepurposeTarget(donor_index)==EXPECT_SUPPORTED);
    assert(!isVapRepurposeTarget(source_index));
    assert(!isVapRepurposed(donor_index));
    assert(vap_svc_is_public(donor_index)==!EXPECT_SUPPORTED);
    assert(!vap_svc_is_private(donor_index));
    assert(!isVapRepurposed(99));
    strcpy(donor.repurposed_vap_name,"private_ssid_2g_compat_other");
    assert(!isVapRepurposed(donor_index));
    strcpy(donor.repurposed_vap_name,WIFI_REPURPOSED_PRIVATE_2G_NAME);
    assert(isVapRepurposed(donor_index)==EXPECT_SUPPORTED);
    assert(vap_svc_is_private(donor_index)==EXPECT_SUPPORTED);
    assert(vap_svc_is_public(9));
    if (EXPECT_SUPPORTED) {
        source.u.bss_info.mac_filter_enable=true;
        source.u.bss_info.mac_filter_mode=0;
        assert(update_repurposed_vap_acl(donor_index,true)==0);
        assert(clear_calls==1 && add_calls==2 && last_mode==2);
        assert(source_rdk.acl_map==&map && map.first==&first && first.next==&second);
        source.u.bss_info.mac_filter_mode=1;
        assert(update_repurposed_vap_acl(donor_index,true)==0 && last_mode==1);
        assert(update_repurposed_vap_acl(donor_index,false)==0 && last_mode==0);
        source_rdk.acl_map=NULL;
        assert(update_repurposed_vap_acl(donor_index,true)==0);
        source_rdk.acl_map=&map;
        fail_clear=1;
        assert(update_repurposed_vap_acl(donor_index,true)==-1);
        fail_clear=0;fail_add=1;
        assert(update_repurposed_vap_acl(donor_index,true)==-1);
        fail_add=0;fail_mode=1;
        assert(update_repurposed_vap_acl(donor_index,true)==-1);
        manager_ptr=NULL;
        assert(!isVapRepurposeTarget(donor_index));
        manager_ptr=&manager;
        donor_index=-1;
        assert(!isVapRepurposeTarget(17));
    } else {
        assert(update_repurposed_vap_acl(donor_index,true)==-1);
        assert(clear_calls==0 && add_calls==0 && mode_calls==0);
    }
    return 0;
}
"""

FUNCTIONS = [
    ("source/core/wifi_ctrl.c", "isVapRepurposeTarget"),
    ("source/core/wifi_ctrl.c", "isVapRepurposed"),
    ("source/core/wifi_ctrl.c", "isVapPrivateNetwork"),
    ("source/core/services/vap_svc_private.c", "vap_svc_is_private"),
    ("source/core/services/vap_svc_public.c", "vap_svc_is_public"),
    ("source/core/services/vap_svc.c", "update_repurposed_vap_acl"),
]
MATRIX = [
    ("XB7_BCM", ["-D_XB7_PRODUCT_REQ_", "-D_COSA_BCM_ARM_"], 1),
    ("XB8", ["-D_XB8_PRODUCT_REQ_"], 1),
    ("XB10", ["-D_XB10_PRODUCT_REQ_"], 1),
    ("XB7_INTEL", ["-D_XB7_PRODUCT_REQ_", "-D_COSA_BCM_ARM_", "-D_INTEL_WAV_"], 0),
    ("unsupported", [], 0),
]


def main():
    source = PRELUDE + "".join(extract(path, name) for path, name in FUNCTIONS) + MAIN
    with tempfile.TemporaryDirectory(prefix=".runtime-test-", dir=ROOT) as directory:
        for nl80211 in (False, True):
            for name, flags, supported in MATRIX:
                binary = str(Path(directory) / "runtime_test")
                args = ["gcc", "-Wall", "-Wextra", "-Werror", "-std=c11", "-x", "c", "-",
                        "-o", binary, "-DEXPECT_SUPPORTED=" + str(supported)] + flags
                if nl80211:
                    args.append("-DNL80211_ACL")
                subprocess.run(args, input=source, text=True, check=True)
                subprocess.run([binary], check=True)
                print("PASS", name, "NL80211 ACL" if nl80211 else "legacy ACL")


if __name__ == "__main__":
    main()
