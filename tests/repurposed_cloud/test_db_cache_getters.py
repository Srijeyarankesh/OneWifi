#!/usr/bin/env python3
"""Test production target-cache getter branches without an OVSDB server.

The actual cache branches are extracted unchanged; unrelated OVSDB fallbacks are
replaced by a counted stub. Full translation-unit compilation checks real types.
Also compile the event enums from HEAD/current and compare existing numeric IDs.
"""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONS = ['wifidb_get_wifi_vap_info', 'wifidb_get_wifi_security_config',
             'wifidb_get_interworking_config', 'wifidb_get_preassoc_ctrl_config',
             'wifidb_get_postassoc_ctrl_config', 'wifidb_get_wifi_security_config_old_mode']

PREAMBLE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define RETURN_OK 0
#define RETURN_ERR -1
typedef struct {int mode;char key[64];} wifi_vap_security_t;
typedef struct {bool interworkingEnabled;int accessNetworkType;char hessid[24];} wifi_InterworkingElement_t;
typedef struct {char vap_name[32];char rssi_up_threshold[16];} wifi_preassoc_control_t;
typedef struct {char vap_name[32];char sampling_count[16];} wifi_postassoc_control_t;
typedef struct {unsigned vap_index;char vap_name[32];union {struct {wifi_vap_security_t security;struct {wifi_InterworkingElement_t interworking;} interworking;wifi_preassoc_control_t preassoc;wifi_postassoc_control_t postassoc;} bss_info;} u;} wifi_vap_info_t;
typedef struct {unsigned vap_index;void *acl_map;bool exists;} rdk_wifi_vap_info_t;
typedef struct {struct {int wifi_prop;} hal_cap;} wifi_mgr_t;
static wifi_mgr_t mgr;
static wifi_vap_info_t cached;
static rdk_wifi_vap_info_t cached_rdk;
static bool missing_vap,missing_rdk;
static int fallback_calls;
static wifi_mgr_t *get_wifimgr_obj(void){return &mgr;}
static int convert_vap_name_to_index(const void *prop,char *name){(void)prop;return name && strcmp(name,"hotspot_secure_2g")==0?8:-1;}
static bool wifidb_is_repurposed_target(char *name){return convert_vap_name_to_index(0,name)==8;}
static wifi_vap_info_t *get_wifidb_vap_parameters(int index){assert(index==8);return missing_vap?NULL:&cached;}
static rdk_wifi_vap_info_t *get_wifidb_rdk_vap_info(int index){assert(index==8);return missing_rdk?NULL:&cached_rdk;}
static int database_fallback(void){fallback_calls++;return 42;}
'''

MAIN = r'''
int main(void){
 char name[]="hotspot_secure_2g";
 wifi_vap_info_t out;rdk_wifi_vap_info_t out_rdk;
 wifi_vap_security_t security;wifi_InterworkingElement_t interworking;
 wifi_preassoc_control_t preassoc;wifi_postassoc_control_t postassoc;
 cached.vap_index=8;strcpy(cached.vap_name,name);cached.u.bss_info.security.mode=8192;
 strcpy(cached.u.bss_info.security.key,"runtime-private-key");cached.u.bss_info.interworking.interworking.interworkingEnabled=false;
 cached.u.bss_info.interworking.interworking.accessNetworkType=4;
 strcpy(cached.u.bss_info.interworking.interworking.hessid,"11:22:33:44:55:66");
 strcpy(cached.u.bss_info.preassoc.rssi_up_threshold,"disabled");
 strcpy(cached.u.bss_info.postassoc.sampling_count,"17");cached_rdk.vap_index=8;cached_rdk.exists=true;cached_rdk.acl_map=&mgr;
 memset(&out,0xa5,sizeof(out));memset(&out_rdk,0xa5,sizeof(out_rdk));
 assert(wifidb_get_wifi_vap_info(name,&out,&out_rdk)==0);
 assert(memcmp(&out,&cached,sizeof(out))==0 && memcmp(&out_rdk,&cached_rdk,sizeof(out_rdk))==0);
 memset(&security,0xa5,sizeof(security));assert(wifidb_get_wifi_security_config(name,&security)==0 && memcmp(&security,&cached.u.bss_info.security,sizeof(security))==0);
 memset(&interworking,0xa5,sizeof(interworking));assert(wifidb_get_interworking_config(name,&interworking)==0 && memcmp(&interworking,&cached.u.bss_info.interworking.interworking,sizeof(interworking))==0);
 memset(&preassoc,0xa5,sizeof(preassoc));assert(wifidb_get_preassoc_ctrl_config(name,&preassoc)==0 && memcmp(&preassoc,&cached.u.bss_info.preassoc,sizeof(preassoc))==0);
 memset(&postassoc,0xa5,sizeof(postassoc));assert(wifidb_get_postassoc_ctrl_config(name,&postassoc)==0 && memcmp(&postassoc,&cached.u.bss_info.postassoc,sizeof(postassoc))==0);
 assert(wifidb_get_wifi_security_config_old_mode(name,8)==8192);
 assert(wifidb_get_wifi_vap_info(name,NULL,&out_rdk)==RETURN_ERR);
 assert(wifidb_get_wifi_vap_info(name,&out,NULL)==RETURN_ERR);
 assert(wifidb_get_wifi_security_config(name,NULL)==RETURN_ERR);
 assert(wifidb_get_interworking_config(name,NULL)==RETURN_ERR);
 assert(wifidb_get_preassoc_ctrl_config(name,NULL)==RETURN_ERR);
 assert(wifidb_get_postassoc_ctrl_config(name,NULL)==RETURN_ERR);
 assert(fallback_calls==0);
 missing_vap=true;
 assert(wifidb_get_wifi_vap_info(name,&out,&out_rdk)==RETURN_ERR);
 assert(wifidb_get_wifi_security_config(name,&security)==RETURN_ERR);
 assert(wifidb_get_interworking_config(name,&interworking)==RETURN_ERR);
 assert(wifidb_get_preassoc_ctrl_config(name,&preassoc)==RETURN_ERR);
 assert(wifidb_get_postassoc_ctrl_config(name,&postassoc)==RETURN_ERR);
 assert(wifidb_get_wifi_security_config_old_mode(name,8)==RETURN_ERR);
 missing_vap=false;missing_rdk=true;assert(wifidb_get_wifi_vap_info(name,&out,&out_rdk)==RETURN_ERR);missing_rdk=false;
 /* Output aliases used by boot loaders must neither deadlock nor zero cache. */
 assert(wifidb_get_wifi_vap_info(name,&cached,&cached_rdk)==0);
 assert(wifidb_get_wifi_security_config(name,&cached.u.bss_info.security)==0);
 assert(cached.u.bss_info.security.mode==8192 && strcmp(cached.u.bss_info.security.key,"runtime-private-key")==0 && cached_rdk.acl_map==&mgr);
 assert(wifidb_get_wifi_security_config("private_ssid_2g",&security)==42 && fallback_calls==1);
 return 0;
}
'''

def getter_branch(source, name):
    match = re.search(r'^int ' + name + r'\([^;]+?\n\{', source, re.M | re.S)
    assert match, name
    signature = match.group()
    start = source.index('    if (wifidb_is_repurposed_target(vap_name)) {', match.end())
    opening = source.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    branch = source[start:end]
    assert 'pthread_mutex_lock' not in branch, 'boot callers can already hold cache lock'
    # old-mode's ordinary fallback uses this argument; the target uses its name.
    unused = '(void)vap_index;' if name.endswith('old_mode') else ''
    return signature + '\n' + branch + '\n    ' + unused + '\n    return database_fallback();\n}\n'

def event_ids(header, tmp, label):
    enums, names = [], []
    for typename in ['wifi_event_type_t', 'wifi_event_subtype_t']:
        m = re.search(r'typedef enum\s*\{([^{}]*)\}\s*' + typename + r';', header, re.S)
        assert m, typename
        enums.append(m.group())
        cleaned = re.sub(r'/\*.*?\*/|//[^\n]*', '', m.group(1), flags=re.S)
        for entry in cleaned.split(','):
            n = re.match(r'\s*(wifi_\w+)', entry)
            if n:
                names.append(n[1])
    c = '#include <stdio.h>\n#define wifi_event_type_base 0x1\n' + '\n'.join(enums)
    c += '\nint main(void){\n' + ''.join('printf("' + name + ' %u\\n", (unsigned)' + name + ');\n' for name in names) + 'return 0;}\n'
    src, exe = tmp / (label + '.c'), tmp / label
    src.write_text(c)
    subprocess.run(['gcc', '-std=c11', '-Wall', '-Werror', str(src), '-o', str(exe)], check=True)
    return {name: int(value) for name, value in (line.split() for line in subprocess.check_output([str(exe)], text=True).splitlines())}

def main():
    source = (ROOT / 'source/db/wifi_db_apis.c').read_text()
    with tempfile.TemporaryDirectory(prefix='.getter-test-', dir=ROOT) as directory:
        tmp = Path(directory)
        src, exe = tmp / 'getters.c', tmp / 'getters'
        src.write_text(PREAMBLE + '\n'.join(getter_branch(source, name) for name in FUNCTIONS) + MAIN)
        subprocess.run(['gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        baseline = subprocess.check_output(['git', 'show', 'HEAD:include/wifi_events.h'], cwd=ROOT, text=True)
        old = event_ids(baseline, tmp, 'events_baseline')
        new = event_ids((ROOT / 'include/wifi_events.h').read_text(), tmp, 'events_current')
        for name, value in old.items():
            if name != 'wifi_event_command_max':
                assert new[name] == value, (name, value, new[name])
        assert new['wifi_event_type_repurposed_vap_rfc'] == old['wifi_event_command_max']
        assert new['wifi_event_type_repurposed_vap_status'] == old['wifi_event_command_max'] + 1
        assert new['wifi_event_command_max'] == old['wifi_event_command_max'] + 2
    print('PASS: six actual DB getter cache branches fill outputs, reject missing outputs/cache, preserve aliased runtime data, and avoid DB/locking; all existing event IDs preserved')

if __name__ == '__main__':
    main()
