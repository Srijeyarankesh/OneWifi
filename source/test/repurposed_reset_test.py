#!/usr/bin/env python3
"""Check successful-reset status replay and absence of success replay after apply failure."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRELUDE = r"""
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#define RETURN_OK 0
#define WIFI_CTRL 0
#define WIFI_DB 0
#define wifi_event_type_command 1
#define wifi_event_type_repurposed_vap_status 2
#define ctrl_webconfig_state_factoryreset_cfg_rsp_pending 4
#define wifi_util_error_print(...) ((void)0)
#define wifi_util_dbg_print(...) ((void)0)
#define wifi_util_info_print(...) ((void)0)
#define system mock_system
typedef struct {struct {bool factory_reset;int webconfig_state;} ctrl;} wifi_mgr_t;
typedef struct {struct {
    int (*cleanup_fn)(void),(*start_wifidb_fn)(void),(*init_tables_fn)(void);
    int (*init_default_value_fn)(void),(*start_monitor_fn)(void);
} desc;} wifi_db_t;
static wifi_mgr_t mgr;
static wifi_db_t db;
static bool enabled=true,consolidated;
static int fail_apply,fail_queue,replays,monitor_calls,services;
wifi_mgr_t *get_wifimgr_obj(void) {return &mgr;}
wifi_db_t *get_wifidb_obj(void) {return &db;}
bool is_db_consolidated(void) {return consolidated;}
int mock_system(const char *command) {assert(command!=NULL);return 0;}
int no_op(void) {return 0;}
int defaults(void) {enabled=false;return 0;}
int monitor(void) {monitor_calls++;return 0;}
int start_wifi_services(void) {services++;assert(!enabled);return fail_apply?-1:0;}
int push_event_to_ctrl_queue(const void *value,unsigned int length,int type,int subtype,void *route) {
    (void)route;assert(length==sizeof(bool) && *(const bool *)value);
    assert(type==wifi_event_type_command && subtype==wifi_event_type_repurposed_vap_status);
    assert(!enabled && services==1 && !fail_apply);
    replays++;return fail_queue?-1:0;
}
"""
MAIN = r"""
static void fixture(void) {
    memset(&mgr,0,sizeof(mgr));enabled=true;consolidated=false;
    fail_apply=fail_queue=replays=monitor_calls=services=0;
    db.desc.cleanup_fn=db.desc.start_wifidb_fn=db.desc.init_tables_fn=no_op;
    db.desc.init_default_value_fn=defaults;db.desc.start_monitor_fn=monitor;
}
int main(void) {
    fixture();process_factory_reset_command(true);
    assert(replays==1 && !enabled && monitor_calls==1 && mgr.ctrl.factory_reset);
    assert(mgr.ctrl.webconfig_state & ctrl_webconfig_state_factoryreset_cfg_rsp_pending);
    fixture();consolidated=true;process_factory_reset_command(true);
    assert(replays==1 && monitor_calls==1);
    fixture();fail_apply=1;process_factory_reset_command(true);
    assert(replays==0 && monitor_calls==1);
    fixture();fail_queue=1;process_factory_reset_command(true);
    assert(replays==1 && !enabled && monitor_calls==1);
    puts("PASS reset replays confirmed status only after successful services; apply/notification failures preserve reset handling");
    return 0;
}
"""


def main():
    text = (ROOT / "source/core/wifi_ctrl_queue_handlers.c").read_text()
    match = re.search(r"^void process_factory_reset_command\([^;]+?\)\n\{", text, re.M)
    if match is None:
        raise AssertionError("process_factory_reset_command")
    function = text[match.start():text.index("\n}", match.end()) + 2]
    with tempfile.TemporaryDirectory(prefix=".reset-test-", dir=ROOT) as directory:
        binary = str(Path(directory) / "reset_test")
        subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-x", "c", "-", "-o", binary],
                       input=PRELUDE + function + MAIN, text=True, check=True)
        subprocess.run([binary], check=True)


if __name__ == "__main__":
    main()
