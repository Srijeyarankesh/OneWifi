/************************************************************************************
  If not stated otherwise in this file or this component's LICENSE file the
  following copyright and licenses apply:

  Copyright 2018 RDK Management

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
**************************************************************************/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <pthread.h>
#include <unistd.h>
#include "collection.h"
#include "wifi_webconfig.h"
#include "wifi_util.h"
#include "wifi_ctrl.h"

webconfig_subdoc_object_t   private_objects[3] = {
    { webconfig_subdoc_object_type_version, "Version" },
    { webconfig_subdoc_object_type_subdoc, "SubDocName" },
    { webconfig_subdoc_object_type_vaps, "WifiVapConfig" },
};

#define REPURPOSED_VAP_NAME VAP_PREFIX_HOTSPOT_SECURE "_2g"

static wifi_vap_info_t *get_private_vap(wifi_platform_property_t *wifi_prop,
    rdk_wifi_radio_t *radios, unsigned int radio_index)
{
    wifi_vap_info_map_t *map = &radios[radio_index].vaps.vap_map;
    unsigned int i;

    for (i = 0; (i < map->num_vaps) && (i < MAX_NUM_VAP_PER_RADIO); i++) {
        if ((map->vap_array[i].vap_name[0] != '\0') &&
            is_vap_private(wifi_prop, map->vap_array[i].vap_index)) {
            return &map->vap_array[i];
        }
    }
    return NULL;
}

static bool is_personal_security_mode(wifi_security_modes_t mode)
{
    return (mode == wifi_security_mode_wpa_personal) || (mode == wifi_security_mode_wpa2_personal) ||
        (mode == wifi_security_mode_wpa_wpa2_personal) || (mode == wifi_security_mode_wpa3_personal) ||
        (mode == wifi_security_mode_wpa3_transition) || (mode == wifi_security_mode_wpa3_compatibility);
}

/* The repurposed VAP has every setting of the private 2.4 GHz VAP (its whole BSS configuration,
 * bridge and, see sync_repurposed_vap_acl(), MAC filter), with these exceptions only:
 * - its identity stays the one of the target VAP (index, name, radio, BSSID),
 * - the security mode is WPA3-Personal-Compatibility with the WPA3 mode encryption and, when the
 *   private 2.4 GHz VAP is open, the passphrase of the private 5 GHz, else 6 GHz, VAP,
 * - MLO and steering (BSS transition) are off, and so is WPS.
 * Where OneWifi tells VAP types apart at runtime, isVapPrivateNetwork() includes it. */
webconfig_error_t derive_repurposed_vap_config(wifi_platform_property_t *wifi_prop,
    rdk_wifi_radio_t *radios, wifi_vap_info_t *vap_info)
{
    wifi_vap_info_t *target, *source, *key_source = NULL;
    wifi_vap_security_t *security;
    int radio_index, vap_array_index, band, pass;
    unsigned int i;
    size_t key_len;

    radio_index = convert_vap_name_to_radio_array_index(wifi_prop, REPURPOSED_VAP_NAME);
    vap_array_index = convert_vap_name_to_array_index(wifi_prop, REPURPOSED_VAP_NAME);
    if ((radio_index < 0) || (vap_array_index < 0)) {
        wifi_util_repurposed_error(WIFI_WEBCONFIG, "no %s vap\n",
            REPURPOSED_VAP_NAME);
        return webconfig_error_not_permitted;
    }
    target = &radios[radio_index].vaps.vap_map.vap_array[vap_array_index];
    source = get_private_vap(wifi_prop, radios, radio_index);
    if (source == NULL) {
        wifi_util_repurposed_error(WIFI_WEBCONFIG, "no private vap on radio %d\n", radio_index);
        return webconfig_error_decode;
    }

    key_source = source;
    if (source->u.bss_info.security.mode == wifi_security_mode_none) {
        // open private 2.4 GHz vap: passphrase of the private 5 GHz, else 6 GHz, vap
        key_source = NULL;
        for (pass = 0; (pass < 2) && (key_source == NULL); pass++) {
            for (i = 0; (i < wifi_prop->numRadios) && (key_source == NULL); i++) {
                if ((convert_radio_index_to_freq_band(wifi_prop, i, &band) != RETURN_OK) ||
                    (band == WIFI_FREQUENCY_2_4_BAND) ||
                    ((band == WIFI_FREQUENCY_6_BAND) != (pass == 1))) {
                    continue;
                }
                key_source = get_private_vap(wifi_prop, radios, i);
                if ((key_source != NULL) &&
                    (key_source->u.bss_info.security.mode == wifi_security_mode_none)) {
                    key_source = NULL;
                }
            }
        }
    }
    if ((key_source == NULL) || !is_personal_security_mode(key_source->u.bss_info.security.mode)) {
        wifi_util_repurposed_error(WIFI_WEBCONFIG, "no private passphrase available\n");
        return webconfig_error_decode;
    }
    // SAE needs a passphrase, a raw 64 hex digit PSK cannot be used
    key_len = strnlen(key_source->u.bss_info.security.u.key.key,
        sizeof(key_source->u.bss_info.security.u.key.key));
    if ((key_len < 8) || (key_len > 63)) {
        wifi_util_repurposed_error(WIFI_WEBCONFIG, "invalid passphrase length:%zu on %s\n",
            key_len, key_source->vap_name);
        return webconfig_error_decode;
    }

    // the vap identity is kept, all the other settings are the private ones
    memcpy(vap_info, target, sizeof(wifi_vap_info_t));
    memcpy(&vap_info->u.bss_info, &source->u.bss_info, sizeof(wifi_front_haul_bss_t));
    memcpy(vap_info->u.bss_info.bssid, target->u.bss_info.bssid, sizeof(vap_info->u.bss_info.bssid));
    snprintf(vap_info->bridge_name, sizeof(vap_info->bridge_name), "%s", source->bridge_name);
    snprintf(vap_info->repurposed_vap_name, sizeof(vap_info->repurposed_vap_name), "%s",
        WIFI_REPURPOSED_PRIVATE_2G_NAME);
    memset(vap_info->repurposed_bridge_name, 0, sizeof(vap_info->repurposed_bridge_name));

    security = &vap_info->u.bss_info.security;
    if (source->u.bss_info.security.mode == wifi_security_mode_none) {
        memset(&security->u, 0, sizeof(security->u));
        snprintf(security->u.key.key, sizeof(security->u.key.key), "%s",
            key_source->u.bss_info.security.u.key.key);
    }
    // the encryption of the WPA3 modes, independent of the private vap encryption which the
    // security migration of the private vaps changes
#ifdef CONFIG_IEEE80211BE
    security->encr = wifi_encryption_aes_gcmp256;
#else
    security->encr = wifi_encryption_aes;
#endif /* CONFIG_IEEE80211BE */
    security->mode = wifi_security_mode_wpa3_compatibility;
    security->u.key.type = wifi_security_key_type_psk_sae;
    security->mfp = wifi_mfp_cfg_disabled;
    security->wpa3_transition_disable = false;

    memset(&vap_info->u.bss_info.wps, 0, sizeof(vap_info->u.bss_info.wps));
    vap_info->u.bss_info.wpsPushButton = 0;
    vap_info->u.bss_info.bssTransitionActivated = false;
    memset(&vap_info->u.bss_info.mld_info, 0, sizeof(vap_info->u.bss_info.mld_info));
    vap_info->u.bss_info.mld_info.common_info.mld_id = 255;
    vap_info->u.bss_info.mld_info.common_info.mld_link_id = 255;

    wifi_util_repurposed_info(WIFI_WEBCONFIG, "vap_index:%d %s derived from %s: enabled:%d "
        "bridge:%s ssid:%s security mode:%d encr:%d passphrase of %s mac filter:%d/%d\n",
        vap_info->vap_index, vap_info->vap_name, source->vap_name, vap_info->u.bss_info.enabled,
        vap_info->bridge_name, vap_info->u.bss_info.ssid, security->mode, security->encr,
        key_source->vap_name, vap_info->u.bss_info.mac_filter_enable,
        vap_info->u.bss_info.mac_filter_mode);
    return webconfig_error_none;
}

webconfig_error_t init_private_subdoc(webconfig_subdoc_t *doc)
{
    doc->num_objects = sizeof(private_objects)/sizeof(webconfig_subdoc_object_t);
    memcpy((unsigned char *)doc->objects, (unsigned char *)&private_objects, sizeof(private_objects));

    return webconfig_error_none;
}


webconfig_error_t access_check_private_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    return webconfig_error_none;
}

webconfig_error_t translate_from_private_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    if (((data->descriptor & webconfig_data_descriptor_translate_to_ovsdb) == webconfig_data_descriptor_translate_to_ovsdb) 
        ||  ((data->descriptor & webconfig_data_descriptor_translate_to_easymesh) == webconfig_data_descriptor_translate_to_easymesh)) {
        if (config->proto_desc.translate_to(webconfig_subdoc_type_private, data) != webconfig_error_none) {
            if ((data->descriptor & webconfig_data_descriptor_translate_to_ovsdb) == webconfig_data_descriptor_translate_to_ovsdb) {
                return webconfig_error_translate_to_ovsdb;
            } else {
                return webconfig_error_translate_to_easymesh;
            }
        }
    } else if ((data->descriptor & webconfig_data_descriptor_translate_to_tr181) == webconfig_data_descriptor_translate_to_tr181) {

    } else {
        // no translation required
    }
    return webconfig_error_none;
}

webconfig_error_t translate_to_private_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    if (((data->descriptor & webconfig_data_descriptor_translate_from_ovsdb) == webconfig_data_descriptor_translate_from_ovsdb)
        ||  ((data->descriptor & webconfig_data_descriptor_translate_from_easymesh) == webconfig_data_descriptor_translate_from_easymesh)) {
        if (config->proto_desc.translate_from(webconfig_subdoc_type_private, data) != webconfig_error_none) {
            if ((data->descriptor & webconfig_data_descriptor_translate_from_ovsdb) == webconfig_data_descriptor_translate_from_ovsdb) {
                return webconfig_error_translate_from_ovsdb;
            } else {
                return webconfig_error_translate_from_easymesh;
            }
        }
    } else if ((data->descriptor & webconfig_data_descriptor_translate_from_tr181) == webconfig_data_descriptor_translate_from_tr181) {

    } else {
        // no translation required
    }
    return webconfig_error_none;
}

webconfig_error_t encode_private_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    cJSON *json;
    cJSON *obj, *obj_array;
    unsigned int i, j;
    wifi_vap_info_map_t *map;
    rdk_wifi_radio_t *radio;
    wifi_vap_info_t *vap;
    rdk_wifi_vap_info_t *rdk_vap;
    webconfig_subdoc_decoded_data_t *params;
    wifi_vap_info_t repurposed_vap;
    rdk_wifi_vap_info_t *repurposed_rdk_vap = NULL;
    char *str;

    params = &data->u.decoded;
    json = cJSON_CreateObject();
    data->u.encoded.json = json;

    cJSON_AddStringToObject(json, "Version", "1.0");
    cJSON_AddStringToObject(json, "SubDocName", "private");

    // ecode private vap objects
    obj_array = cJSON_CreateArray();
    cJSON_AddItemToObject(json, "WifiVapConfig", obj_array);

    for (i = 0; i < params->num_radios; i++) {
        radio = &params->radios[i];
        map = &radio->vaps.vap_map;
        for (j = 0; j < map->num_vaps; j++) {
            vap = &map->vap_array[j];
            rdk_vap = &radio->vaps.rdk_vap_array[j];
            if (is_vap_private(&params->hal_cap.wifi_prop, vap->vap_index) && (strlen(vap->vap_name) != 0)) {
                obj = cJSON_CreateObject();
                cJSON_AddItemToArray(obj_array, obj);
                if (encode_private_vap_object(vap, rdk_vap, obj) != webconfig_error_none) {
                    wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: Failed to encode private vap object\n", __func__, __LINE__);
                    cJSON_Delete(json);
                    return webconfig_error_encode;

                }
            }
        }
    }

    // encode repurposed vap request, enabled it is derived from the private vaps above
    if (params->repurposed_vap == webconfig_repurposed_vap_enable) {
        if (derive_repurposed_vap_config(&params->hal_cap.wifi_prop, params->radios,
                &repurposed_vap) != webconfig_error_none) {
            wifi_util_repurposed_error(WIFI_WEBCONFIG, "Failed to derive repurposed vap\n");
            cJSON_Delete(json);
            return webconfig_error_encode;
        }
        repurposed_rdk_vap = &params->radios[convert_vap_name_to_radio_array_index(
            &params->hal_cap.wifi_prop, REPURPOSED_VAP_NAME)].vaps.rdk_vap_array[
            convert_vap_name_to_array_index(&params->hal_cap.wifi_prop, REPURPOSED_VAP_NAME)];
    }
    if (encode_repurposed_vap_object(params->repurposed_vap, &repurposed_vap, repurposed_rdk_vap,
            json) != webconfig_error_none) {
        wifi_util_repurposed_error(WIFI_WEBCONFIG, "Failed to encode repurposed vap object\n");
        cJSON_Delete(json);
        return webconfig_error_encode;
    }

    str = cJSON_Print(json);

    if (str == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: Failed to encode private subdoc\n", __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_encode;
    }

    data->u.encoded.raw = (webconfig_subdoc_encoded_raw_t)calloc(strlen(str) + 1, sizeof(char));
    if (data->u.encoded.raw == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG,"%s:%d Failed to allocate memory.\n", __func__,__LINE__);
        cJSON_free(str);
        cJSON_Delete(json);
        return webconfig_error_encode;
    }

   memcpy(data->u.encoded.raw, str, strlen(str) + 1);

   if (wifi_util_webconfig_is_dbg_enabled()) {
        char *dbg = strdup(data->u.encoded.raw);
        if (dbg != NULL) {
            json_param_obscure(dbg, "Passphrase");
            json_param_obscure(dbg, "WpsConfigPin");
            wifi_util_dbg_print(WIFI_WEBCONFIG, "%s:%d: Encoded JSON:\n%s\n", __func__, __LINE__, dbg);
            free(dbg);
        }
    }
    cJSON_free(str);
    cJSON_Delete(json);
    wifi_util_info_print(WIFI_WEBCONFIG, "%s:%d: encode success\n", __func__, __LINE__);
    return webconfig_error_none;
}

webconfig_error_t decode_private_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    webconfig_subdoc_t  *doc;
    cJSON *obj_vaps;
    cJSON *obj, *obj_vap;
    unsigned int i, j, size, radio_index, vap_array_index;
    unsigned int presence_count = 0;
    unsigned int num_private_ssid;
    wifi_vap_name_t vap_names[MAX_NUM_RADIOS];
    char *name;
    char *str;
    wifi_vap_info_t *vap_info;
    rdk_wifi_vap_info_t *rdk_vap_info;
    cJSON *json = data->u.encoded.json;
    webconfig_subdoc_decoded_data_t *params;

    params = &data->u.decoded;
    doc = &config->subdocs[data->type];
    /* get list of private SSID */
    num_private_ssid = get_list_of_private_ssid(&params->hal_cap.wifi_prop, MAX_NUM_RADIOS, vap_names);

    wifi_util_dbg_print(WIFI_WEBCONFIG, "%s:%d - Number of private SSID found = %u\n", __func__, __LINE__, num_private_ssid);

    if (wifi_util_webconfig_is_dbg_enabled()) {
        str =  cJSON_Print(json);

        if (str != NULL) {
            json_param_obscure(str, "Passphrase");
            json_param_obscure(str, "WpsConfigPin");
            wifi_util_dbg_print(WIFI_WEBCONFIG, "%s:%d: decoded JSON:\n%s\n", __func__, __LINE__, str);
            cJSON_free(str);
        }
    }
    for (i = 0; i < doc->num_objects; i++) {
        if ((cJSON_GetObjectItem(json, doc->objects[i].name)) == NULL) {
            wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: object:%s not present, validation failed\n",
                __func__, __LINE__, doc->objects[i].name);
            cJSON_Delete(json);
            wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
            return webconfig_error_invalid_subdoc;
        }
    }

    // decode VAP objects
    obj_vaps = cJSON_GetObjectItem(json, "WifiVapConfig");
    if (cJSON_IsArray(obj_vaps) == false) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: vap object not present\n", __func__, __LINE__);
        cJSON_Delete(json);
        wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
        return webconfig_error_invalid_subdoc;
    }

    size = cJSON_GetArraySize(obj_vaps);
    if (size < MIN_NUM_RADIOS || size > MAX_NUM_RADIOS) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: Not correct number of vap objects: %d, expected: %d\n",
            __func__, __LINE__, size, params->hal_cap.wifi_prop.numRadios);
        cJSON_Delete(json);
        wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
        return webconfig_error_invalid_subdoc;
    }

    presence_count = 0;

    for (i = 0; i < size; i++) {
        obj_vap = cJSON_GetArrayItem(obj_vaps, i);
        // check presence of all vap names
        if ((obj = cJSON_GetObjectItem(obj_vap, "VapName")) == NULL) {
            cJSON_Delete(json);
            wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
            return webconfig_error_invalid_subdoc;
        }

        for (j = 0; j < size; j++) {
            if (strncmp(cJSON_GetStringValue(obj), vap_names[j], strlen(vap_names[j])) == 0) {
                presence_count++;
            }
        }
    }
//    if (presence_count < MIN_NUM_RADIOS || presence_count > MAX_NUM_RADIOS) {
    if (presence_count != num_private_ssid) {
        cJSON_Delete(json);
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: vap object not present\n", __func__, __LINE__);
        wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
        return webconfig_error_invalid_subdoc;
    }

    // first set the structure to all 0
//    memset(&params->radios, 0, sizeof(rdk_wifi_radio_t)*params->hal_cap.wifi_prop.numRadios);
    for (i = 0; i < params->hal_cap.wifi_prop.numRadios; i++) {
        params->radios[i].vaps.vap_map.num_vaps = params->hal_cap.wifi_prop.radiocap[i].maxNumberVAPs;
        params->radios[i].vaps.num_vaps = params->hal_cap.wifi_prop.radiocap[i].maxNumberVAPs;
    }

    for (i = 0; i < size; i++) {
        obj_vap = cJSON_GetArrayItem(obj_vaps, i);
        name = cJSON_GetStringValue(cJSON_GetObjectItem(obj_vap, "VapName"));
        radio_index = convert_vap_name_to_radio_array_index(&params->hal_cap.wifi_prop, name);
        vap_array_index = convert_vap_name_to_array_index(&params->hal_cap.wifi_prop, name);
        if (((int)radio_index < 0) || ((int)vap_array_index < 0)) {
            wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: Invalid index\n", __func__, __LINE__);
            continue;
        }
        vap_info = &params->radios[radio_index].vaps.vap_map.vap_array[vap_array_index];
        rdk_vap_info = &params->radios[radio_index].vaps.rdk_vap_array[vap_array_index];
        if (!strncmp(name, "private_ssid", strlen("private_ssid"))) {
            memset(vap_info, 0, sizeof(wifi_vap_info_t));
            if (decode_private_vap_object(obj_vap, vap_info, rdk_vap_info,
                    &params->hal_cap.wifi_prop) != webconfig_error_none) {
                wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: VAP object validation failed\n",
                    __func__, __LINE__);
                cJSON_Delete(json);
                wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
                return webconfig_error_decode;
            }
        }
    }

    // decode repurposed vap request, an enable request carries the repurposed vap configuration
    if (decode_repurposed_vap_object(json, &params->repurposed_vap) != webconfig_error_none) {
        cJSON_Delete(json);
        return webconfig_error_decode;
    }
    if (params->repurposed_vap == webconfig_repurposed_vap_enable) {
        obj_vap = cJSON_GetObjectItem(cJSON_GetArrayItem(cJSON_GetObjectItem(json,
            "RepurposedVapConfig"), 0), "VapConfig");
        name = cJSON_GetStringValue(cJSON_GetObjectItem(obj_vap, "VapName"));
        if ((name == NULL) || (strcmp(name, REPURPOSED_VAP_NAME) != 0)) {
            wifi_util_repurposed_error(WIFI_WEBCONFIG, "repurposed vap object not present\n");
            cJSON_Delete(json);
            return webconfig_error_invalid_subdoc;
        }
        radio_index = convert_vap_name_to_radio_array_index(&params->hal_cap.wifi_prop, name);
        vap_array_index = convert_vap_name_to_array_index(&params->hal_cap.wifi_prop, name);
        if (((int)radio_index < 0) || ((int)vap_array_index < 0)) {
            wifi_util_repurposed_error(WIFI_WEBCONFIG, "Invalid index for %s\n", name);
            cJSON_Delete(json);
            return webconfig_error_invalid_subdoc;
        }
        vap_info = &params->radios[radio_index].vaps.vap_map.vap_array[vap_array_index];
        rdk_vap_info = &params->radios[radio_index].vaps.rdk_vap_array[vap_array_index];
        memset(vap_info, 0, sizeof(wifi_vap_info_t));
        if ((decode_private_vap_object(obj_vap, vap_info, rdk_vap_info,
                &params->hal_cap.wifi_prop) != webconfig_error_none) ||
            (strcmp(vap_info->repurposed_vap_name, WIFI_REPURPOSED_PRIVATE_2G_NAME) != 0)) {
            wifi_util_repurposed_error(WIFI_WEBCONFIG, "repurposed vap object validation failed\n");
            cJSON_Delete(json);
            return webconfig_error_decode;
        }
        wifi_util_repurposed_info(WIFI_WEBCONFIG, "vap_index:%d %s decoded: enabled:%d bridge:%s "
            "security mode:%d\n", vap_info->vap_index, vap_info->vap_name,
            vap_info->u.bss_info.enabled, vap_info->bridge_name,
            vap_info->u.bss_info.security.mode);
    }

    wifi_util_info_print(WIFI_WEBCONFIG, "%s:%d: decode success\n", __func__, __LINE__);

    cJSON_Delete(json);
    return webconfig_error_none;
}
