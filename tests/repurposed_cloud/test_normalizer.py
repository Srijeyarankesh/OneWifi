#!/usr/bin/env python3
"""Compile actual private metadata/normalizer functions with cJSON and mocked I/O.

Run from any directory: python3 tests/repurposed_cloud/test_normalizer.py
The cloud field merge/parser are production source; HAL, queue, legacy parser and
current-private encoding are explicit boundaries, not hardware integration tests.
"""
from pathlib import Path
import copy
import json
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads((ROOT / 'tests/repurposed_cloud/current_private.json').read_text())
CLOUD = json.loads((ROOT / 'tests/repurposed_cloud/incoming_private.json').read_text())

def extract(path, name):
    source = (ROOT / path).read_text()
    match = re.search(r'^(?:static )?[\w* ]+\b' + name + r'\([^;]+?\n\{.*?^\}', source, re.M | re.S)
    if not match:
        raise AssertionError(f'{name}: source function missing')
    return match.group()

PREAMBLE = r'''
#include <assert.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#define RETURN_OK 0
#define RETURN_ERR -1
#define MAX_NUM_RADIOS 3
#define WIFI_CTRL 0
#define WIFI_HAL_FAILURE 2
#define VALIDATION_FALIED 1
#define wifi_util_error_print(...) ((void)0)
typedef enum {webconfig_error_none,webconfig_error_invalid_subdoc,webconfig_error_encode} webconfig_error_t;
typedef enum {webconfig_subdoc_type_private,webconfig_subdoc_type_home} webconfig_subdoc_type_t;
typedef enum {wifi_vap_mode_ap,wifi_vap_mode_sta} wifi_vap_mode_t;
enum {wifi_event_type_webconfig,wifi_event_webconfig_set_data_webconfig};
typedef struct {int unused;} webconfig_t;
typedef struct {struct {struct {char *raw;} encoded;} u;char legacy_ssid[64];} webconfig_subdoc_data_t;
typedef struct {webconfig_t webconfig;} wifi_ctrl_t;
typedef struct {int ErrorCode;char ErrorMsg[256];} Err,*pErr;
static wifi_ctrl_t ctrl;
static char *baseline,*queued_raw;
static int queued,legacy_calls,encodes;
typedef struct {max_align_t alignment;size_t magic;} hook_header_t;
static long hook_calls,hook_live,hook_fail_at;
static void *hook_malloc(size_t size){
 hook_calls++;if(hook_fail_at && hook_calls==hook_fail_at)return NULL;
 hook_header_t *h=malloc(sizeof(*h)+size);if(!h)return NULL;h->magic=0xc150a11;hook_live++;return h+1;
}
static void hook_free(void *ptr){
 if(!ptr){return;}
 hook_header_t *h=(hook_header_t*)ptr-1;assert(h->magic==0xc150a11);h->magic=0;hook_live--;free(h);
}
static void setup_hooks(void){
 if(getenv("CUSTOM_HOOKS")){cJSON_Hooks hooks={hook_malloc,hook_free};cJSON_InitHooks(&hooks);}
 if(getenv("HOOK_FAIL_AT"))hook_fail_at=strtol(getenv("HOOK_FAIL_AT"),NULL,10);
}
static wifi_ctrl_t *get_wifictrl_obj(void){return &ctrl;}
static pErr create_execRetVal(void){return getenv("FAIL_EXEC")?NULL:calloc(1,sizeof(Err));}
static void webconfig_init_subdoc_data(webconfig_subdoc_data_t *d){(void)d;}
static void webconfig_data_free(webconfig_subdoc_data_t *d){free(d->u.encoded.raw);d->u.encoded.raw=NULL;}
static webconfig_error_t encode_private_subdoc(webconfig_t *c,webconfig_subdoc_data_t *d){
 (void)c;encodes++;cJSON *j=cJSON_Parse(baseline);if(!j)return webconfig_error_encode;
 if(d->legacy_ssid[0])cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(j,"WifiVapConfig"),0),"SSID",cJSON_CreateString(d->legacy_ssid));
 char *printed=cJSON_PrintUnformatted(j);d->u.encoded.raw=printed?strdup(printed):NULL;cJSON_free(printed);cJSON_Delete(j);return d->u.encoded.raw?webconfig_error_none:webconfig_error_encode;
}
static int update_vap_info_with_blob_info(void *blob,void *amenities,webconfig_subdoc_data_t *d,const char *prefix,bool managed,pErr e){
 (void)amenities;(void)prefix;(void)managed;(void)e;legacy_calls++;
 cJSON *j=cJSON_Parse(blob),*ssid=cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(j,"private_ssid_2g"),"SSID");
 if(!cJSON_IsString(ssid)){cJSON_Delete(j);return RETURN_ERR;}
 snprintf(d->legacy_ssid,sizeof(d->legacy_ssid),"%s",ssid->valuestring);cJSON_Delete(j);return RETURN_OK;
}
static int push_event_to_ctrl_queue(void *raw,unsigned len,int type,int sub,void *x){
 (void)type;(void)sub;(void)x;queued++;queued_raw=strndup(raw,len);return queued_raw?RETURN_OK:RETURN_ERR;
}
static int push_blob_data(webconfig_subdoc_data_t *d,webconfig_subdoc_type_t type){(void)d;(void)type;return RETURN_OK;}
static char *normalizer_strdup(const char *raw){return getenv("FAIL_NORMALIZED_COPY")?NULL:strdup(raw);}
#define strdup normalizer_strdup

'''
MAIN = r'''
static char *read_file(const char *name){FILE *f=fopen(name,"rb");assert(f);assert(fseek(f,0,SEEK_END)==0);long n=ftell(f);rewind(f);char *s=calloc((size_t)n+1,1);assert(s);assert(fread(s,1,(size_t)n,f)==(size_t)n);fclose(f);return s;}
int main(int argc,char **argv){
 assert(argc==4);setup_hooks();baseline=read_file(argv[2]);char *input=read_file(argv[3]);int rc;
 if(strcmp(argv[1],"handler")==0){pErr e=private_home_exec_common_handler(input,"private_ssid",webconfig_subdoc_type_private);rc=e?e->ErrorCode:99;free(e);if(queued_raw)puts(queued_raw);}
 else {cJSON *j=cJSON_Parse(input);webconfig_subdoc_data_t d={0};
  if(strcmp(argv[1],"metadata")==0){bool present=false,enabled=false;rc=decode_repurposed_vap_config(j,&present,&enabled);printf("{\"present\":%s,\"enabled\":%s}\n",present?"true":"false",enabled?"true":"false");}
  else {rc=encode_private_cloud_request(&d,j,strcmp(argv[1],"legacy")!=0);if(rc==0)puts(d.u.encoded.raw);webconfig_data_free(&d);}
  cJSON_Delete(j);
 }
 fprintf(stderr,"RESULT %d %d %d %d\n",rc,queued,legacy_calls,encodes);free(queued_raw);free(input);free(baseline);fprintf(stderr,"HOOKS %ld %ld\n",hook_calls,hook_live);assert(hook_live==0);cJSON_InitHooks(NULL);return 0;
}
'''

def run():
    bodies = [extract('source/webconfig/wifi_webconfig_private.c', 'decode_repurposed_vap_config')]
    bodies += [extract('source/core/wifi_multidoc_webconfig.c', name) for name in
               ['merge_private_blob_object', 'encode_private_cloud_request', 'private_home_exec_common_handler']]
    count = 0
    with tempfile.TemporaryDirectory(prefix='.cloud-test-', dir=ROOT) as td:
        tmp = Path(td)
        src, exe = tmp / 'normalizer.c', tmp / 'normalizer'
        src.write_text(PREAMBLE + '\n'.join(bodies) + MAIN)
        subprocess.run(['gcc', '-D_GNU_SOURCE', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-I' + str(ROOT / 'tests/deps'), str(src),
                        str(ROOT / 'tests/deps/cJSON.c'), '-o', str(exe)], check=True)

        def invoke(mode, value, expected=0, fail_exec=False, extra_env=None):
            nonlocal count
            inp = tmp / 'incoming.json'
            inp.write_text(value if isinstance(value, str) else json.dumps(value))
            env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1')
            if fail_exec:
                env['FAIL_EXEC'] = '1'
            if extra_env:
                env.update(extra_env)
            result = subprocess.run([str(exe), mode, str(ROOT / 'tests/repurposed_cloud/current_private.json'), str(inp)],
                                    capture_output=True, text=True, env=env)
            assert result.returncode == 0, result.stderr
            m = re.search(r'RESULT (-?\d+) (\d+) (\d+) (\d+)', result.stderr)
            assert m, result.stderr
            rc, queued, legacy, encodes = map(int, m.groups())
            assert (rc == 0) == (expected == 0), (mode, rc, expected, value)
            if expected:
                assert queued == 0, 'invalid request reached controller queue'
            count += 1
            hook_match = re.search(r'HOOKS (\d+) (\d+)', result.stderr)
            invoke.hook_calls = int(hook_match[1]) if hook_match else 0
            return json.loads(result.stdout) if result.stdout else None, (rc, queued, legacy, encodes)

        assert invoke('metadata', {})[0] == {'present': False, 'enabled': False}
        for enabled in [False, True]:
            assert invoke('metadata', {'RepurposedVapConfig': [{'Enabled': enabled}]})[0] == {'present': True, 'enabled': enabled}
        for bad in [None, True, {}, [], [{'Enabled': True}, {'Enabled': False}], [{}], [{'Enabled': 1}], [{'Enabled': 'true'}], [{'Enabled': True, 'Other': 0}]]:
            invoke('metadata', {'RepurposedVapConfig': bad}, expected=1)
        invoke('metadata', '{"RepurposedVapConfig":[{"Enabled":true}],"RepurposedVapConfig":[{"Enabled":false}]}', expected=1)
        invoke('metadata', '{"RepurposedVapConfig":[{"Enabled":true,"Enabled":false}]}', expected=1)
        invoke('metadata', '[]', expected=1)

        out, stats = invoke('new', CLOUD)
        assert len(out['WifiVapConfig']) == 3 and out['WifiVapConfig'][2] == BASE['WifiVapConfig'][2]
        def overlay(old, new):
            result = copy.deepcopy(old)
            for key, val in new.items():
                result[key] = overlay(result[key], val) if isinstance(val, dict) and isinstance(result.get(key), dict) else copy.deepcopy(val)
            return result
        for i in [0, 1]:
            assert out['WifiVapConfig'][i] == overlay(BASE['WifiVapConfig'][i], CLOUD['WifiVapConfig'][i]), i
        assert out['RepurposedVapConfig'] == [{'Enabled': True}]
        assert stats[1:3] == (0, 0)
        assert invoke('handler', CLOUD)[1][1:3] == (1, 0)
        for enabled in [False, None]:
            cloud = copy.deepcopy(CLOUD)
            if enabled is None:
                del cloud['RepurposedVapConfig']
            else:
                cloud['RepurposedVapConfig'][0]['Enabled'] = enabled
            out, _ = invoke('new', cloud)
            assert ('RepurposedVapConfig' in out) == (enabled is not None)
            if enabled is not None:
                assert out['RepurposedVapConfig'][0]['Enabled'] is False
        for edit in ['duplicate_vap', 'radio_mismatch', 'radio_fraction', 'unknown_name', 'bad_ssid', 'bad_security', 'bad_enabled', 'bad_vapmode', 'marker']:
            cloud = copy.deepcopy(CLOUD)
            vap = cloud['WifiVapConfig'][0]
            if edit == 'duplicate_vap': cloud['WifiVapConfig'][1] = copy.deepcopy(vap)
            elif edit == 'radio_mismatch': vap['RadioIndex'] = 1
            elif edit == 'radio_fraction': vap['RadioIndex'] = 0.5
            elif edit == 'unknown_name': vap['VapName'] = 'hotspot_secure_2g'
            elif edit == 'bad_ssid': vap['SSID'] = 123
            elif edit == 'bad_security': vap['Security'] = []
            elif edit == 'bad_enabled': vap['Enabled'] = 'true'
            elif edit == 'bad_vapmode': vap['VapMode'] = 1
            elif edit == 'marker': vap['RepurposedVapName'] = 'private_ssid_2g_repurposed'
            invoke('handler', cloud, expected=1)
        encoded = json.dumps(CLOUD)
        invoke('handler', encoded.replace('"VapName": "private_ssid_2g"', '"VapName": "private_ssid_2g", "VapName": "private_ssid_2g"', 1), expected=1)
        invoke('handler', encoded.replace('"VenueType": 4', '"VenueType": 4, "VenueType": 4', 1), expected=1)
        invoke('handler', encoded.replace('"Version": "1.0"', '"Version": "1.0", "Version": "1.0"', 1), expected=1)
        invoke('handler', {**CLOUD, 'RepurposedVapConfig': [{'Enabled': 'false'}]}, expected=1)
        legacy = {'private_ssid_2g': {'SSID': 'LEGACY_ACCEPTED'}, 'private_security_2g': {'ModeEnabled': 'WPA2-Personal', 'Passphrase': 'legacy-password'}}
        out, stats = invoke('handler', legacy)
        assert stats[1:3] == (1, 1) and out['WifiVapConfig'][0]['SSID'] == 'LEGACY_ACCEPTED'
        assert 'RepurposedVapConfig' not in out
        for enabled in [False, True]:
            out, stats = invoke('handler', {**legacy, 'RepurposedVapConfig': [{'Enabled': enabled}]})
            assert stats[1:3] == (1, 1) and out['RepurposedVapConfig'][0]['Enabled'] is enabled
        invoke('handler', CLOUD, expected=1, fail_exec=True)
        # Hook allocations are deliberately interior pointers: passing a printed
        # cJSON buffer to libc free would fail immediately under AddressSanitizer.
        invoke('handler', CLOUD, extra_env={'CUSTOM_HOOKS': '1'})
        allocation_count = invoke.hook_calls
        invoke('handler', CLOUD, expected=1, extra_env={'CUSTOM_HOOKS': '1', 'FAIL_NORMALIZED_COPY': '1'})
        for failure_at in [1, 10, 100, allocation_count - 1, allocation_count]:
            invoke('handler', CLOUD, expected=1, extra_env={'CUSTOM_HOOKS': '1', 'HOOK_FAIL_AT': str(failure_at)})

    print(f'PASS: {count} actual-C metadata/normalizer/handler cases under ASan/UBSan; field preservation, 6GHz merge, validation, legacy routing and allocation-error cleanup')

if __name__ == '__main__':
    run()
