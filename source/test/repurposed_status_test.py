#!/usr/bin/env python3
"""Execute the actual status command case with failed-recovery and clean runtime caches."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRELUDE = r"""
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#define wifi_event_type_repurposed_vap_status 1
typedef struct {bool ctrl_initialized;} wifi_ctrl_t;
typedef struct {struct {int wifi_prop;} hal_cap;} wifi_mgr_t;
typedef struct {bool force_apply;} rdk_wifi_vap_info_t;
static wifi_mgr_t mgr;
static rdk_wifi_vap_info_t rdk;
static int target=17,notifications;
static bool marker=true,rdk_present=true,last_value;
wifi_mgr_t *get_wifimgr_obj(void) {return &mgr;}
int convert_vap_name_to_index(int *prop,const char *name) {(void)prop;(void)name;return target;}
rdk_wifi_vap_info_t *get_wifidb_rdk_vap_info(int index) {assert(index==17);return rdk_present?&rdk:NULL;}
bool isVapRepurposed(unsigned int index) {assert(index==17);return marker;}
int publish_repurposed_vap_status(bool value) {notifications++;last_value=value;return 0;}
"""
MAIN = r"""
int main(void) {
    wifi_ctrl_t ctrl={.ctrl_initialized=true};
    rdk.force_apply=true;
    replay(&ctrl);assert(notifications==0);
    rdk.force_apply=false;
    replay(&ctrl);assert(notifications==1 && last_value);
    marker=false;
    replay(&ctrl);assert(notifications==2 && !last_value);
    rdk_present=false;
    replay(&ctrl);assert(notifications==2);
    rdk_present=true;ctrl.ctrl_initialized=false;
    replay(&ctrl);assert(notifications==2);
    ctrl.ctrl_initialized=true;target=-1;
    replay(&ctrl);assert(notifications==2);
    puts("PASS status replay suppresses uncertain/missing/uninitialized state and reports recovered active or clean dormant state");
    return 0;
}
"""


def main():
    text = (ROOT / "source/core/wifi_ctrl_queue_handlers.c").read_text()
    start = text.index("    case wifi_event_type_repurposed_vap_status:")
    match = re.search(r"^    case ", text[start + 1:], re.M)
    if match is None:
        raise AssertionError("next command case")
    case = text[start:start + 1 + match.start()]
    function = "static void replay(wifi_ctrl_t *ctrl) {\nswitch (wifi_event_type_repurposed_vap_status) {\n" + case + "}\n}\n"
    with tempfile.TemporaryDirectory(prefix=".status-test-", dir=ROOT) as directory:
        binary = str(Path(directory) / "status_test")
        subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-x", "c", "-", "-o", binary],
                       input=PRELUDE + function + MAIN, text=True, check=True)
        subprocess.run([binary], check=True)


if __name__ == "__main__":
    main()
