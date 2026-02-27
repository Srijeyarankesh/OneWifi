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

webconfig_subdoc_object_t   ignitewifi_config_objects[3] = {
    { webconfig_subdoc_object_type_version, "Version" },
    { webconfig_subdoc_object_type_subdoc, "SubDocName" },
    { webconfig_subdoc_object_type_ignitewifi_config, "IgniteWiFiConfig" }
};

webconfig_error_t init_ignitewifi_subdoc(webconfig_subdoc_t *doc)
{
    doc->num_objects = sizeof(ignitewifi_config_objects)/sizeof(webconfig_subdoc_object_t);
    memcpy((unsigned char *)doc->objects, (unsigned char *)&ignitewifi_config_objects, sizeof(ignitewifi_config_objects));

    return webconfig_error_none;
}

webconfig_error_t access_check_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    return webconfig_error_none;
}

webconfig_error_t translate_from_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    return webconfig_error_none;
}

webconfig_error_t translate_to_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    return webconfig_error_none;
}

webconfig_error_t encode_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    cJSON *json;
    cJSON *config_array;
    cJSON *config_item;
    char *str;
    webconfig_subdoc_decoded_data_t *params;

    if (data == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: NULL data Pointer\n", __func__, __LINE__);
        return webconfig_error_encode;
    }

    params = &data->u.decoded;
    if (params == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: NULL Pointer\n", __func__, __LINE__);
        return webconfig_error_encode;
    }

    json = cJSON_CreateObject();
    if (json == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: json create object failed\n", __func__, __LINE__);
        return webconfig_error_encode;
    }

    data->u.encoded.json = json;

    cJSON_AddStringToObject(json, "Version", "1.0");
    cJSON_AddStringToObject(json, "SubDocName", "ignitewifi");

    config_array = cJSON_CreateArray();
    if (config_array == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: json create array failed\n", __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_encode;
    }
    cJSON_AddItemToObject(json, "IgniteWiFiConfig", config_array);

    config_item = cJSON_CreateObject();
    if (config_item == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: json create object failed\n", __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_encode;
    }
    cJSON_AddItemToArray(config_array, config_item);
    cJSON_AddNumberToObject(config_item, "LinkQualityThreshold",
        params->config.global_parameters.ignite_link_quality_threshold);

    str = cJSON_Print(json);

    data->u.encoded.raw = (webconfig_subdoc_encoded_raw_t)calloc(strlen(str) + 1, sizeof(char));
    if (data->u.encoded.raw == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG,"%s:%d Failed to allocate memory.\n", __func__,__LINE__);
        cJSON_free(str);
        cJSON_Delete(json);
        return webconfig_error_encode;
    }

    wifi_util_dbg_print(WIFI_WEBCONFIG,"encoded str is %s\n", str);
    memcpy(data->u.encoded.raw, str, strlen(str));
    cJSON_free(str);
    cJSON_Delete(json);
    wifi_util_info_print(WIFI_WEBCONFIG, "%s:%d: encode success\n", __func__, __LINE__);
    return webconfig_error_none;
}

webconfig_error_t decode_ignitewifi_subdoc(webconfig_t *config, webconfig_subdoc_data_t *data)
{
    webconfig_subdoc_decoded_data_t *params;
    cJSON *json;
    cJSON *config_array;
    cJSON *first_item;
    cJSON *threshold_obj;

    params = &data->u.decoded;
    if (params == NULL) {
        return webconfig_error_decode;
    }

    json = data->u.encoded.json;
    if (json == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: NULL json pointer\n", __func__, __LINE__);
        return webconfig_error_decode;
    }

    config_array = cJSON_GetObjectItem(json, "IgniteWiFiConfig");
    if (config_array == NULL || !cJSON_IsArray(config_array) || cJSON_GetArraySize(config_array) == 0) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: IgniteWiFiConfig not present or empty\n",
            __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_decode;
    }

    first_item = cJSON_GetArrayItem(config_array, 0);
    if (first_item == NULL) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: IgniteWiFiConfig first item is NULL\n",
            __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_decode;
    }

    threshold_obj = cJSON_GetObjectItem(first_item, "LinkQualityThreshold");
    if (threshold_obj == NULL || !cJSON_IsNumber(threshold_obj)) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: LinkQualityThreshold not present or invalid\n",
            __func__, __LINE__);
        cJSON_Delete(json);
        return webconfig_error_decode;
    }

    float link_quality_threshold = (float)threshold_obj->valuedouble;
    if (link_quality_threshold < 0.0 || link_quality_threshold > 1.0) {
        wifi_util_error_print(WIFI_WEBCONFIG, "%s:%d: LinkQualityThreshold %f out of range [0.0, 1.0]\n",
            __func__, __LINE__, link_quality_threshold);
        cJSON_Delete(json);
        return webconfig_error_decode;
    }

    params->config.global_parameters.ignite_link_quality_threshold = link_quality_threshold;

    cJSON_Delete(json);
    wifi_util_info_print(WIFI_WEBCONFIG, "%s:%d: decode success, LinkQualityThreshold=%f\n",
        __func__, __LINE__, link_quality_threshold);
    return webconfig_error_none;
}
