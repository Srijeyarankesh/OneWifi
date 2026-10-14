#!/usr/bin/env python3
"""Test the Repurposed2GVap object of the cloud private blob and its private apply.

Run from any directory: python3 tests/repurposed_cloud/test_repurposed_2g_vap.py

The production functions are extracted unchanged and compiled with the vendored cJSON:
- decode_repurposed_vap_object() (wifi_decoder.c), shared by the cloud blob and the private subdoc,
- ignore_inapplicable_repurposed_vap_enable() and private_home_exec_common_handler()
  (wifi_multidoc_webconfig.c), the cloud privatessid blob handler,
- webconfig_hal_private_vap_apply() (wifi_ctrl_webconfig.c), the private subdoc apply.
The private vap blob parsing, the subdoc encoding, the HAL and the queue are counted stubs.
"""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def extract(path, name):
    source = (ROOT / path).read_text()
    match = re.search(r'^(?:static )?[\w* ]+\b' + name + r'\([^;]+?\n\{.*?^\}', source, re.M | re.S)
    if not match:
        raise AssertionError(f'{name}: source function missing in {path}')
    return match.group()


def header_definitions():
    header = (ROOT / 'include/wifi_webconfig.h').read_text()
    define = re.search(r'^#define WIFI_REPURPOSED_VAP_OBJECT .*$', header, re.M)
    enum = re.search(r'^typedef enum \{\n    webconfig_repurposed_vap_unchanged.*?\} webconfig_repurposed_vap_t;',
                     header, re.M | re.S)
    if not define or not enum:
        raise AssertionError('Repurposed2GVap definitions missing in include/wifi_webconfig.h')
    return define.group() + '\n' + enum.group() + '\n'


PREAMBLE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#define RETURN_OK 0
#define RETURN_ERR -1
#define UINT unsigned int
#define MAX_VAP 8
#define MAX_NUM_RADIOS 3
#define WIFI_CTRL 0
#define WIFI_WEBCONFIG 1
#define WIFI_MGR 2
#define VALIDATION_FALIED 1
#define WIFI_HAL_FAILURE 2
#define wifi_util_error_print(module, ...) ((void)(module), fprintf(stderr, __VA_ARGS__))
#define wifi_util_info_print(module, ...) ((void)(module), fprintf(stderr, __VA_ARGS__))
#define wifi_util_repurposed_error(module, ...) ((void)(module), fprintf(stderr, "SREESH: " __VA_ARGS__))
#define wifi_util_repurposed_info(module, ...) ((void)(module), fprintf(stderr, "SREESH: " __VA_ARGS__))
typedef enum { webconfig_error_none = 0, webconfig_error_decode = 2, webconfig_error_not_permitted = 9 } webconfig_error_t;
typedef enum { webconfig_subdoc_type_private = 0, webconfig_subdoc_type_home = 1 } webconfig_subdoc_type_t;
'''

TYPES = r'''
typedef struct { unsigned char opaque[64]; } wifi_vap_info_t;
typedef struct { int numRadios; } wifi_platform_property_t;
typedef struct { wifi_platform_property_t wifi_prop; } wifi_hal_capability_t;
typedef struct { int unused; } rdk_wifi_radio_t;
typedef struct { wifi_hal_capability_t hal_cap; rdk_wifi_radio_t radios[MAX_NUM_RADIOS];
    webconfig_repurposed_vap_t repurposed_vap; } webconfig_subdoc_decoded_data_t;
typedef struct { struct { webconfig_subdoc_decoded_data_t decoded; } u; } webconfig_subdoc_data_t;
typedef struct { int ErrorCode; char ErrorMsg[128]; } Err, *pErr;
typedef struct { int unused; } wifi_ctrl_t;
typedef struct { int unused; } wifi_hal_cap_t;
typedef struct { wifi_hal_cap_t hal_cap; } wifi_mgr_t;
typedef struct { bool repurposed_vap_enable; } wifi_rfc_dml_parameters_t;

/* cloud handler stubs */
static int blob_parse_ret, derive_ret, push_ret;
static int derive_calls, push_calls, blob_parse_calls;
static webconfig_repurposed_vap_t pushed_request;
static pErr create_execRetVal(void) { pErr e = calloc(1, sizeof(Err)); return e; }
static void webconfig_init_subdoc_data(webconfig_subdoc_data_t *data) { memset(data, 0, sizeof(*data)); }
static int update_vap_info_with_blob_info(void *blob, void *amenities, webconfig_subdoc_data_t *data,
    const char *prefix, bool managed, pErr ret)
{ (void)blob; (void)amenities; (void)data; (void)prefix; (void)managed; (void)ret; blob_parse_calls++; return blob_parse_ret; }
static webconfig_error_t derive_repurposed_vap_config(wifi_platform_property_t *prop, rdk_wifi_radio_t *radios,
    wifi_vap_info_t *vap)
{ (void)prop; (void)radios; memset(vap, 0, sizeof(*vap)); derive_calls++; return (webconfig_error_t)derive_ret; }
static int push_blob_data(webconfig_subdoc_data_t *data, webconfig_subdoc_type_t type)
{ (void)type; push_calls++; pushed_request = data->u.decoded.repurposed_vap; return push_ret; }

/* private apply stubs */
static wifi_mgr_t mgr;
static wifi_rfc_dml_parameters_t rfc;
static int apply_by_name_calls, apply_by_name_ret, request_apply_ret, migrate_ret, request_apply_calls;
static wifi_mgr_t *get_wifimgr_obj(void) { return &mgr; }
static unsigned int getTotalNumberVAPs(void) { return 2; }
#define VAP_INDEX(cap, index) ((void)(cap), (index))
static bool isVapPrivate(unsigned int index) { return index < 2; }
static char *getVAPName(unsigned int index) { static char names[2][32] = { "private_ssid_2g", "private_ssid_5g" }; return names[index]; }
static int webconfig_hal_vap_apply_by_name(wifi_ctrl_t *ctrl, webconfig_subdoc_decoded_data_t *data, char **names,
    unsigned int num)
{ (void)ctrl; (void)data; assert(num == 2 && strcmp(names[0], "private_ssid_2g") == 0); apply_by_name_calls++; return apply_by_name_ret; }
static wifi_rfc_dml_parameters_t *get_wifi_db_rfc_parameters(void) { return &rfc; }
static int webconfig_hal_repurposed_vap_request_apply(wifi_ctrl_t *ctrl, webconfig_subdoc_decoded_data_t *data)
{ (void)ctrl; (void)data; request_apply_calls++; if (request_apply_ret == RETURN_OK && data->repurposed_vap == webconfig_repurposed_vap_enable) rfc.repurposed_vap_enable = true; return request_apply_ret; }
static bool webconfig_repurposed_vap_security_migrate(webconfig_subdoc_decoded_data_t *data) { (void)data; return migrate_ret; }
'''

MAIN = r'''
typedef struct { const char *blob; webconfig_subdoc_type_t type; int error; webconfig_repurposed_vap_t pushed; int derived; } blob_case_t;

static void run_blob(const blob_case_t *c, int line)
{
    pErr ret;
    int pushes = push_calls, derives = derive_calls;

    ret = private_home_exec_common_handler((void *)c->blob, "private_ssid", c->type);
    if (ret == NULL || ret->ErrorCode != c->error) {
        fprintf(stderr, "case at line %d: error %d expected %d\n", line, ret ? ret->ErrorCode : -1, c->error);
        assert(0);
    }
    if (c->error == 0) {
        assert(push_calls == pushes + 1 && pushed_request == c->pushed);
    } else {
        assert(push_calls == pushes);
        assert(strcmp(ret->ErrorMsg, "Invalid Repurposed2GVap") == 0);
    }
    assert(derive_calls == derives + c->derived);
    free(ret);
}

#define BLOB(blob, type, error, pushed, derived) do { blob_case_t c = { blob, type, error, pushed, derived }; run_blob(&c, __LINE__); } while (0)
#define P webconfig_subdoc_type_private
#define H webconfig_subdoc_type_home
#define UNCHANGED webconfig_repurposed_vap_unchanged
#define ENABLE webconfig_repurposed_vap_enable
#define DISABLE webconfig_repurposed_vap_disable

int main(void)
{
    const char *base = "\"private_ssid_2g\":{\"SSID\":\"Home\",\"Enable\":true,\"SSIDAdvertisementEnabled\":true}";
    char blob[512];
    webconfig_subdoc_decoded_data_t data;
    wifi_ctrl_t ctrl;

    /* absent: ignored, the private blob is applied as before */
    snprintf(blob, sizeof(blob), "{%s}", base);
    BLOB(blob, P, 0, UNCHANGED, 0);
    /* present: accepted */
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":true}}", base);
    BLOB(blob, P, 0, ENABLE, 1);
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":false}}", base);
    BLOB(blob, P, 0, DISABLE, 0);
    /* present without Enabled: ignored */
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{}}", base);
    BLOB(blob, P, 0, UNCHANGED, 0);
    /* Enabled is a boolean, as the Enable of the private vaps: anything else fails the blob */
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":\"true\"}}", base);
    BLOB(blob, P, 1, UNCHANGED, 0);
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":\"false\"}}", base);
    BLOB(blob, P, 1, UNCHANGED, 0);
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":1}}", base);
    BLOB(blob, P, 1, UNCHANGED, 0);
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":null}}", base);
    BLOB(blob, P, 1, UNCHANGED, 0);
    /* the object itself must be an object */
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":[{\"Enabled\":true}]}", base);
    BLOB(blob, P, 1, UNCHANGED, 0);
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":true}", base);
    BLOB(blob, P, 1, UNCHANGED, 0);
    /* the former RepurposedVapConfig key is not a request anymore */
    snprintf(blob, sizeof(blob), "{%s,\"RepurposedVapConfig\":[{\"Enabled\":true}]}", base);
    BLOB(blob, P, 0, UNCHANGED, 0);
    /* an enable this device cannot apply does not fail the private blob */
    derive_ret = webconfig_error_not_permitted;
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":true}}", base);
    BLOB(blob, P, 0, UNCHANGED, 1);
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":false}}", base);
    BLOB(blob, P, 0, DISABLE, 0);
    derive_ret = webconfig_error_none;
    /* the home blob does not carry it */
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":true}}", base);
    BLOB(blob, H, 0, UNCHANGED, 0);
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":\"x\"}}", base);
    BLOB(blob, H, 0, UNCHANGED, 0);
    /* a private vap blob error is reported as before, Repurposed2GVap is not looked at */
    blob_parse_ret = -1;
    snprintf(blob, sizeof(blob), "{%s,\"Repurposed2GVap\":{\"Enabled\":true}}", base);
    {
        int pushes = push_calls;
        pErr ret = private_home_exec_common_handler(blob, "private_ssid", P);
        assert(ret != NULL && ret->ErrorCode == VALIDATION_FALIED && push_calls == pushes);
        assert(strcmp(ret->ErrorMsg, "Invalid Repurposed2GVap") != 0);
        free(ret);
    }
    blob_parse_ret = 0;
    /* a queue failure is reported as before */
    push_ret = -1;
    snprintf(blob, sizeof(blob), "{%s}", base);
    {
        pErr ret = private_home_exec_common_handler(blob, "private_ssid", P);
        assert(ret != NULL && ret->ErrorCode == WIFI_HAL_FAILURE);
        free(ret);
    }
    push_ret = 0;
    assert(private_home_exec_common_handler(NULL, "private_ssid", P) == NULL);

    /* the private apply: a failed private vap apply fails it as before */
    memset(&data, 0, sizeof(data));
    apply_by_name_ret = RETURN_ERR;
    assert(webconfig_hal_private_vap_apply(&ctrl, &data) == RETURN_ERR && request_apply_calls == 0);
    apply_by_name_ret = RETURN_OK;
    /* a failed enable request is not queued again */
    request_apply_ret = RETURN_ERR;
    data.repurposed_vap = ENABLE;
    apply_by_name_calls = 0;
    assert(webconfig_hal_private_vap_apply(&ctrl, &data) == RETURN_OK && apply_by_name_calls == 1);
    assert(rfc.repurposed_vap_enable == false);
    /* a failed disable, or a failed reconciliation, is queued again as before */
    data.repurposed_vap = DISABLE;
    assert(webconfig_hal_private_vap_apply(&ctrl, &data) == RETURN_ERR);
    data.repurposed_vap = UNCHANGED;
    assert(webconfig_hal_private_vap_apply(&ctrl, &data) == RETURN_ERR);
    /* a successful enable migrates the private vaps once, as before */
    request_apply_ret = RETURN_OK;
    migrate_ret = true;
    data.repurposed_vap = ENABLE;
    apply_by_name_calls = 0;
    assert(webconfig_hal_private_vap_apply(&ctrl, &data) == RETURN_OK && apply_by_name_calls == 2);
    /* already enabled: no migration */
    apply_by_name_calls = 0;
    assert(webconfig_hal_private_vap_apply(&ctrl, &data) == RETURN_OK && apply_by_name_calls == 1);

    printf("Repurposed2GVap tests passed\n");
    return 0;
}
'''


def run():
    bodies = [extract('source/webconfig/wifi_decoder.c', 'decode_repurposed_vap_object'),
              extract('source/core/wifi_multidoc_webconfig.c', 'ignore_inapplicable_repurposed_vap_enable'),
              extract('source/core/wifi_multidoc_webconfig.c', 'private_home_exec_common_handler'),
              extract('source/core/wifi_ctrl_webconfig.c', 'webconfig_hal_private_vap_apply')]
    source = PREAMBLE + header_definitions() + TYPES + '\n'.join(bodies) + MAIN
    with tempfile.TemporaryDirectory(prefix='.repurposed-2g-vap-test-', dir=ROOT) as td:
        tmp = Path(td)
        src, exe = tmp / 'test.c', tmp / 'test'
        src.write_text(source)
        subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-sanitize-recover=all', '-I', str(ROOT / 'tests/deps'),
                        str(src), str(ROOT / 'tests/deps/cJSON.c'), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stdout + result.stderr)
            raise SystemExit(result.returncode)
        print(result.stdout, end='')


if __name__ == '__main__':
    run()
