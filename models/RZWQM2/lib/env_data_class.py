import json
import os
import statistics
from datetime import datetime
import re
import csv


def split_for_value(line):
    value_obj = []
    for i, val in enumerate(line):
        value_obj.append({'day': i + 2, "value": val})
    return value_obj


def split_for_value_hly(line):
    value_obj = []
    for i, val in enumerate(line):
        if value_string_to_num_hly(val):
            value_obj.append(value_string_to_num_hly(val))
    return value_obj


def value_string_to_num(s):
    if s == '000000' or s == '-99999M':
        return 999
    else:
        res = int(s.lstrip('0')) / 10
        return res


def value_string_to_num_hly(s):
    if s == '000000' or s == '-99999':
        return None
    else:
        res = int(s.lstrip('0')) / 10
        return res


def split_functions(s):
    splitted = re.split('\s|[T]|[M](?=[-])|[M]', s)
    if len(splitted) > 31:
        splitted = splitted[:31]
    final_obj = {}
    prefix = splitted[0]
    final_obj['station_id'] = prefix[0:7]
    final_obj['year'] = prefix[7:11]
    final_obj['month'] = prefix[11:13]
    final_obj['elementnum'] = prefix[13:16]
    value_obj = [{'day': '1', 'value': prefix[16:23]}]
    del splitted[0]
    value_obj.extend(split_for_value(splitted))
    final_obj['values'] = value_obj
    return final_obj


def split_functions_hly(s):
    splitted = re.split('\s|U|V|W|Y|Z|X|P|[M](?=[-])|[M]', s)
    del splitted[-1]
    if len(splitted) > 31:
        splitted = splitted[:31]
    final_obj = {}
    prefix = splitted[0]
    final_obj['station_id'] = prefix[0:7]
    final_obj['year'] = prefix[7:11]
    final_obj['month'] = prefix[11:13]
    final_obj['day'] = prefix[13:15]
    final_obj['elementnum'] = prefix[15:18]
    if ([prefix[18:23]]) != '000000' or ([prefix[18:23]]) != '-99999':
        value_obj = [int(prefix[18:23])]
    del splitted[0]
    value_obj.extend(split_for_value_hly(splitted))
    final_obj['values'] = statistics.mean(value_obj)
    return final_obj


def read_path_in_dir(path):
    path_to_data_folder = path
    all_path = []
    for file in os.listdir(path_to_data_folder):
        if file.endswith(".txt"):
            the_path = os.path.join(path, file)
            all_path.append(the_path)
    return all_path

def read_path_in_dir_csv(path):
    path_to_data_folder = path
    all_path = []
    for file in os.listdir(path_to_data_folder):
        if file.endswith(".csv"):
            the_path = os.path.join(path, file)
            all_path.append(the_path)
    return all_path


def read_json_path_in_dir(path):
    path_to_data_folder = path
    all_path = []
    for file in os.listdir(path_to_data_folder):
        if file.endswith(".json"):
            the_path = os.path.join(path, file)
            all_path.append(the_path)
    return all_path


def read_json_from_path(array_of_path):
    res = {}
    for val in array_of_path:
        name = re.search('[A-Z0-9]{7}(?=.)', val)[0]
        with open(val) as f:
            data = json.load(f)
            res[name] = data
    return res


def check_stations_return_duration(json_res, crop_station_list, save_name, jsonorcsv):
    duration = {}
    for val in json_res:
        if val in crop_station_list:
            temp = {}
            for depth in json_res[val]:
                keys = list(json_res[val][depth].keys())
                first = keys[0]
                last = keys[-1]
                first_date = first[-4:]
                last_date = last[-4:]
                temp[depth] = [int(first_date), int(last_date)]
            # print(temp)
            duration[val] = temp
    if jsonorcsv == 'json':
        with open(save_name, 'w') as f:
            json.dump(duration, f)
    elif jsonorcsv == 'csv':
        with open(save_name, 'w') as csv_file:
            writer = csv.writer(csv_file)
            for key, value in duration.items():
                writer.writerow([key, value])

def dump_data_for_each_station(res):
    # dump the data for each station
    for the_key in res:
        with open('./Sorted_hly11/'+str(the_key)+'.json', 'w') as f:
            json.dump(res[the_key], f)

class env_dly:
    def __init__(self, directory, dly):
        self.directory = directory
        self.dly = dly
        self.paths = []
        self.data = {}

    @classmethod
    def read_data_from_path(cls, array_of_path):
        final_res = {}
        for val in array_of_path:
            with open(val) as f:
                lines = [line.rstrip('\n') for line in f]
            for each_line in lines:
                # for each line, the values are stored in a dict of {date:val}
                temp_data_save = {}
                res = split_functions(each_line)
                year = res['year']
                month = res['month']
                values = res['values']
                for count, var_data in enumerate(values):
                    date_str = year + ',' + month + ',' + str(count + 1)
                    try:
                        date_object = datetime.strptime(date_str, '%Y,%m,%d')
                        temp_data_save[date_object.strftime('%m/%d/%Y')] = value_string_to_num(var_data['value'])
                    except Exception as e:
                        print(e)
                        print(each_line)
                        print(date_str)
                        continue
                # check if the station_id exists in the current dict
                if res['station_id'] in final_res.keys():
                    # check if the station_id contains the depth variable
                    if res['elementnum'] in final_res[res['station_id']].keys():
                        final_res[res['station_id']][res['elementnum']].update(temp_data_save)
                    else:
                        final_res[res['station_id']][res['elementnum']] = {}
                        final_res[res['station_id']][res['elementnum']].update(temp_data_save)
                else:
                    final_res[res['station_id']] = {}
                    final_res[res['station_id']][res['elementnum']] = {}
                    final_res[res['station_id']][res['elementnum']].update(temp_data_save)
        return final_res


class env_hly:
    def __init__(self, directory, hly):
        self.directory = directory
        self.dly = hly
        self.paths = []
        self.data = {}

    @classmethod
    def read_data_from_path(cls, array_of_path):
        final_res = {}
        for val in array_of_path:
            with open(val) as f:
                lines = [line.rstrip('\n') for line in f]
            for each_line in lines:
                # for each line, the values are stored in a dict of {date:val}
                try:
                    temp_data_save = {}
                    res = split_functions_hly(each_line)
                    year = res['year']
                    month = res['month']
                    day = res['day']
                    value = res['values']
                    date_str = year + ',' + month + ',' + str(day)
                    date_object = datetime.strptime(date_str, '%Y,%m,%d')
                    temp_data_save[date_object.strftime('%m/%d/%Y')] = value
                except Exception as e:
                    print(e)
                    # print(each_line)
                    # print(date_str)
                    continue
                # check if the station_id exists in the current dict
                if res['station_id'] in final_res.keys():
                    # check if the station_id contains the depth variable
                    if res['elementnum'] in final_res[res['station_id']].keys():
                        final_res[res['station_id']][res['elementnum']].update(temp_data_save)
                    else:
                        final_res[res['station_id']][res['elementnum']] = {}
                        final_res[res['station_id']][res['elementnum']].update(temp_data_save)
                else:
                    final_res[res['station_id']] = {}
                    final_res[res['station_id']][res['elementnum']] = {}
                    final_res[res['station_id']][res['elementnum']].update(temp_data_save)
        return final_res
