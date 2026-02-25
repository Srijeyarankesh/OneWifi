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

webconfig_subdoc_object_t   ignitewifi_objects[3] = {
    { webconfig_subdoc_object_type_version, "Version" },
    { webconfig_subdoc_object_type_subdoc, "SubDocName" },
    { webconfig_subdoc_object_type_ignitewifi_config, "IgniteWiFiConfig" },
};

webconfig_error_t init_ignitewifi_subdoc(webconfig_subdoc_t *doc)
{
    doc->num_objects = sizeof(ignitewifi_objects)/sizeof(webconfig_subdoc_object_t);
    memcpy((unsigned char *)doc->objects, (unsigned char *)&ignitewifi_objects, sizeof(ignitewifi_objects));

    return webconfig_error_none;
}

webconfig_error_t access_check_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    return webconfig_error_none;
}

webconfig_error_t translate_from_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    if ((data->descriptor & webconfig_data_descriptor_translate_to_ovsdb) == webconfig_data_descriptor_translate_to_ovsdb) {
        if (config->proto_desc.translate_to(webconfig_subdoc_type_ignitewifi, data) != webconfig_error_none) {
            return webconfig_error_translate_to_ovsdb;
        }
    } else if ((data->descriptor & webconfig_data_descriptor_translate_to_tr181) == webconfig_data_descriptor_translate_to_tr181) {

    } else {
        // no translation required
    }
    return webconfig_error_none;
}

webconfig_error_t translate_to_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    if ((data->descriptor & webconfig_data_descriptor_translate_from_ovsdb) == webconfig_data_descriptor_translate_from_ovsdb) {
        if (config->proto_desc.translate_from(webconfig_subdoc_type_ignitewifi, data) != webconfig_error_none) {
            return webconfig_error_translate_from_ovsdb;
        }
    } else if ((data->descriptor & webconfig_data_descriptor_translate_from_tr181) == webconfig_data_descriptor_translate_from_tr181) {

    } else {
        // no translation required
    }
    return webconfig_error_none;
}

webconfig_error_t encode_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    cJSON *json;
    cJSON *obj, *obj_array;
    unsigned int i, j;
    wifi_vap_info_map_t *map;
    wifi_vap_info_t *vap;
    rdk_wifi_radio_t *radio;
    webconfig_subdoc_decoded_data_t *params;
    char *str;

    params = &data->u.decoded;
    json = cJSON_CreateObject();
    if (json == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: Failed to create JSON object\n", __func__, __LINE__);
        return webconfig_error_encode;
    }
    data->u.encoded.json = json;

    cJSON_AddStringToObject(json, "Version", "1.0");
    cJSON_AddStringToObject(json, "SubDocName", "ignitewifi");

    obj_array = cJSON_CreateArray();
    cJSON_AddItemToObject(json, "IgniteWiFiConfig", obj_array);

    for (i = 0; i < params->num_radios; i++) {
        radio = &params->radios[i];
        map = &radio->vaps.vap_map;

        for (j = 0; j < map->num_vaps; j++) {
            vap = &map->vap_array[j];

            if (is_vap_mesh_sta(&params->hal_cap.wifi_prop, vap->vap_index) &&
                (strlen(vap->vap_name) != 0)) {

                obj = cJSON_CreateObject();
                cJSON_AddStringToObject(obj, "VapName", vap->vap_name);
                cJSON_AddNumberToObject(obj, "LinkQualityThreshold",
                    (double)vap->link_quality_threshold);
                cJSON_AddItemToArray(obj_array, obj);

                wifi_util_dbg_print(WIFI_WEBCONFIG,
                    "%s:%d: Encoded vap=%s link_quality_threshold=%f\n",
                    __func__, __LINE__, vap->vap_name, vap->link_quality_threshold);
            }
        }
    }

    str = cJSON_Print(json);
    if (str == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: cJSON_Print failed\n", __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_encode;
    }

    data->u.encoded.raw = (webconfig_subdoc_encoded_raw_t)calloc(strlen(str) + 1, sizeof(char));
    if (data->u.encoded.raw == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: Failed to allocate memory\n", __func__, __LINE__);
        cJSON_free(str);
        cJSON_Delete(json);
        return webconfig_error_encode;
    }

    memcpy(data->u.encoded.raw, str, strlen(str));

    wifi_util_dbg_print(WIFI_WEBCONFIG, "%s:%d: Encoded JSON:\n%s\n", __func__, __LINE__, str);
    cJSON_free(str);
    cJSON_Delete(json);
    wifi_util_info_print(WIFI_WEBCONFIG, "%s:%d: encode success\n", __func__, __LINE__);
    return webconfig_error_none;
}

webconfig_error_t decode_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    webconfig_subdoc_t *doc;
    cJSON *obj_config;
    cJSON *obj;
    cJSON *threshold_obj;
    unsigned int i, size;
    unsigned int radio_index, vap_array_index;
    wifi_vap_name_t vap_names[MAX_NUM_RADIOS];
    unsigned int num_mesh_sta;
    wifi_vap_info_t *vap_info;
    cJSON *json = data->u.encoded.json;
    webconfig_subdoc_decoded_data_t *params;
    char *str;
    float link_quality_threshold = 0.0;

    params = &data->u.decoded;
    doc = &config->subdocs[data->type];

    num_mesh_sta = get_list_of_mesh_sta(&params->hal_cap.wifi_prop, MAX_NUM_RADIOS, vap_names);

    wifi_util_dbg_print(WIFI_WEBCONFIG, "%s:%d: Number of mesh STA VAPs = %u\n",
        __func__, __LINE__, num_mesh_sta);

    str = cJSON_Print(json);
    if (str != NULL) {
        wifi_util_dbg_print(WIFI_WEBCONFIG, "%s:%d: Incoming JSON:\n%s\n", __func__, __LINE__, str);
        cJSON_free(str);
    }

    for (i = 0; i < doc->num_objects; i++) {
        if ((cJSON_GetObjectItem(json, doc->objects[i].name)) == NULL) {
            wifi_util_error_print(WIFI_WEBCONFIG,
                "%s:%d: object:%s not present, validation failed\n",
                __func__, __LINE__, doc->objects[i].name);
            cJSON_Delete(json);
            wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
            return webconfig_error_invalid_subdoc;
        }
    }

    obj_config = cJSON_GetObjectItem(json, "IgniteWiFiConfig");
    if (cJSON_IsArray(obj_config) == false) {
        wifi_util_error_print(WIFI_WEBCONFIG,
            "%s:%d: IgniteWiFiConfig is not an array\n", __func__, __LINE__);
        cJSON_Delete(json);
        wifi_util_error_print(WIFI_WEBCONFIG, "%s\n", (char *)data->u.encoded.raw);
        return webconfig_error_invalid_subdoc;
    }

    size = cJSON_GetArraySize(obj_config);
    if (size == 0) {
        wifi_util_error_print(WIFI_WEBCONFIG,
            "%s:%d: IgniteWiFiConfig array is empty\n", __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_invalid_subdoc;
    }

    obj = cJSON_GetArrayItem(obj_config, 0);
    if (obj == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG,
            "%s:%d: Failed to get first IgniteWiFiConfig element\n", __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_invalid_subdoc;
    }

    threshold_obj = cJSON_GetObjectItem(obj, "LinkQualityThreshold");
    if (threshold_obj == NULL || !cJSON_IsNumber(threshold_obj)) {
        wifi_util_error_print(WIFI_WEBCONFIG,
            "%s:%d: LinkQualityThreshold not present or not a number\n", __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_invalid_subdoc;
    }

    link_quality_threshold = (float)threshold_obj->valuedouble;

    if (link_quality_threshold < 0.0 || link_quality_threshold > 1.0) {
        wifi_util_error_print(WIFI_WEBCONFIG,
            "%s:%d: LinkQualityThreshold value %f out of valid range [0.0, 1.0]\n",
            __func__, __LINE__, link_quality_threshold);
        cJSON_Delete(json);
        return webconfig_error_invalid_subdoc;
    }

    wifi_util_info_print(WIFI_WEBCONFIG,
        "%s:%d: Decoded LinkQualityThreshold=%f, applying to %u mesh STA VAPs\n",
        __func__, __LINE__, link_quality_threshold, num_mesh_sta);

    for (i = 0; i < num_mesh_sta; i++) {
        radio_index = convert_vap_name_to_radio_array_index(&params->hal_cap.wifi_prop, vap_names[i]);
        vap_array_index = convert_vap_name_to_array_index(&params->hal_cap.wifi_prop, vap_names[i]);

        if ((int)radio_index < 0 || (int)vap_array_index < 0) {
            wifi_util_error_print(WIFI_WEBCONFIG,
                "%s:%d: Invalid index for vap=%s radio_index=%d vap_array_index=%d\n",
                __func__, __LINE__, vap_names[i], radio_index, vap_array_index);
            continue;
        }

        vap_info = &params->radios[radio_index].vaps.vap_map.vap_array[vap_array_index];
        vap_info->link_quality_threshold = link_quality_threshold;

        wifi_util_dbg_print(WIFI_WEBCONFIG,
            "%s:%d: Set link_quality_threshold=%f for vap=%s\n",
            __func__, __LINE__, link_quality_threshold, vap_names[i]);
    }

    cJSON_Delete(json);
    wifi_util_info_print(WIFI_WEBCONFIG, "%s:%d: decode success\n", __func__, __LINE__);
    return webconfig_error_none;
}
