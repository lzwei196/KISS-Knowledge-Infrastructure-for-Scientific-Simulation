# from db_functions import read_file_path_in_dir_custom
import csv
import json
import os
from datetime import datetime, timedelta
from pprint import pprint

from ca_freeze_thaw.db.db_commands import select_one_value_from_a_col_with_condition, \
    select_multiple_col_based_on_date_range
from data_handle.find_the_index_for_variable import find_the_index
from csv_parsing import read_the_file_split
# example format for a file name:en_climate_hourly_QC_702FHL8_12-2020_P1H
from db_functions import read_file_path_in_dir_custom
import statistics

filename = 'en_climate_hourly_QC_702FHL8_12-2020_P1H.csv'
path = 'C:/cygwin64/home/lzwei/'


def name_to_date(path, dailyorhourly='daily'):
    name = path.split('_')
    # 6th in the list is the date
    print(name)
    if dailyorhourly == 'hourly':
        date = datetime.strptime(name[5], '%d-%Y')
    elif dailyorhourly == 'daily':
        date = datetime.strptime(name[5], '%Y')
    return date


def read_the_file(path, spliter_boo, split_delimeter=","):
    with open(path, encoding="utf8", errors='ignore') as f:
        lines = [line.rstrip('\n') for line in f]
    parsed_data_all = []
    for data in lines:
        if spliter_boo:
            parsed_data = data.split(split_delimeter)
        else:
            parsed_data = data.split()
        parsed_data_all.append(parsed_data)
    return parsed_data_all


def write_to_csv(path, s):
    with open(path, 'a', encoding='utf8', newline='') as output_file:
        fc = csv.DictWriter(output_file,
                            fieldnames=s[0].keys(),
                            )
        fc.writeheader()
        fc.writerows(s)


def write_to_to_csv_list_of_lists(path, s):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(s)


def write_to_to_csv_list_of_lists_a(path, s):
    with open(path, "a", newline="", encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(s)


def read_all_and_write_to_one(path, write_to_name, dailyorhourly, targeting_hourly_var='RH'):
    all_data = []
    paths = read_file_path_in_dir_custom(path, '.csv')
    header = ''
    for count, val in enumerate(paths):
        the_date = name_to_date(val, dailyorhourly)
        data = read_the_file_split(os.path.join(path, val))
        if count == 0:
            # get the header value
            header = data[0]
        del data[0]
        if dailyorhourly == 'hourly':
            data = sort_hourly(data, '%Y-%m-%d %H:%M', header, targeting_hourly_var)
            data = [[x, statistics.mean(data[x])] for x in data]
        all_data.append({'the_date': the_date, 'data': data})
    # sort the data based on date
    all_data.sort(key=lambda x: x['the_date'])
    # add header, the first line
    all_data[0]['data'].insert(0, header)
    for val in all_data:
        write_to_to_csv_list_of_lists_a(write_to_name, val['data'])


# 6 year, 7 month, 8 day, 9 hours,
def rzwqm_format(path):
    # Rzwqm requires the date format to be %d/%m/%Y
    lines = read_the_file(path, False)
    dates = []
    # the list is taken in
    for line in lines:
        # date = datetime.strptime((line.split(',')[4]).split()[0], '%Y-%m-%d')
        date = datetime.strptime((line.split(',')[4]), '%Y-%m-%d %H:%M')
        dates.append(date.strftime('%d/%m/%Y'))
    write_to_csv('rzwqm_met.csv', dates)

    # the format requires the date to be the first column
    # missing dates will be filled up
    # column_num has to be 0, which is the date column



def check_missing_day(path, fmt='%Y-%m-%d', create_csv=False):
    # this function is to fill up the random missing days in the ECCC met files
    # fmt = '%d/%m/%Y'
    parsed_data_all = read_the_file(path)
    title = parsed_data_all[0]
    var_position = find_the_column(title)
    days = 0
    del parsed_data_all[0]
    # all the lines has been splited into list of lists.
    for count, splitted_data in enumerate(parsed_data_all):
        try:
            date_current = datetime.strptime((parsed_data_all[count])[var_position['date']], fmt)
            date_next = datetime.strptime((parsed_data_all[count + 1])[var_position['date']], fmt)
            days = (date_next - date_current).days
        except Exception as e:
            pass
        if days > 1:
            print(days)
            print(f"Missing date at {date_current}")
            num = count
            for i in range(days - 1):
                date_current = date_current + timedelta(days=1)
                parsed_data_all.insert(num + 1, [str(date_current.strftime('%d/%m/%Y'))])
                num = num + 1
    # push the first line back in
    parsed_data_all.insert(0, title)
    desired_data = desired_columns(parsed_data_all)
    if create_csv:
        write_to_to_csv_list_of_lists('test_check_data.csv', desired_data)
    return parsed_data_all, var_position


def desired_columns(data):
    title = data[0]
    column_dict = find_the_column(title)
    data_with_only_desired_fields = []
    for val in data:
        temp_list = append_to_column(val, column_dict)
        data_with_only_desired_fields.append(temp_list)
    return data_with_only_desired_fields


def append_to_column(data, title):
    temp_list = [data[0]]
    for count, val in enumerate(data):
        if count in title.values():
            temp_list.append(data[count])
    return temp_list


def find_the_column(title):
    eccc_var = {}

    for count, val in enumerate(title):
        find = find_the_index(val)
        if find.find_min_temp():
            eccc_var['min'] = count
        elif find.find_max_temp():
            eccc_var['max'] = count
        elif find.find_rain():
            eccc_var['rain'] = count
        elif find.find_snow():
            eccc_var['snow'] = count
        elif find.find_RH():
            eccc_var['RH'] = count
        elif find.find_date():
            eccc_var['date'] = count
        elif find.find_solar():
            eccc_var['solar'] = count
        elif find.find_wind():
            eccc_var['wind'] = count
        elif find.find_temp():
            eccc_var['temp'] = count
        elif find.find_snowfall():
            eccc_var['snowfall'] = count

    return eccc_var


def fill_up_missing_data_using_nasa_data(eccc_data_path, nasa_data_path, nasa_hourly_data_path, eccc_date_column, fmt,
                                         name):
    # this function takes two input, the data from eccc with missing data that filled up with only the dates the
    # second input is the nasa hourly data the hourly nasa data should also be used if the max and min temp for the
    # daily ECCC data is needed eccc data: 0:date 1:MIN_TEMPERATURE 2 MAX_TEMPERATURE 3 TOTAL_PRECIPITATION 4RH %
    # 5wind km/day 6 solar radiation, snow 7 nasa hourly data: 0 date, 1:temp, 2:RH, 3:pressure, 4:wind speed,
    # 6:rainfall, 11:solar, 8:snow depth
    eccc_data = check_missing_day(eccc_data_path, eccc_date_column, fmt)
    nasa_daily_data = read_the_file_split(nasa_data_path)
    del nasa_daily_data[0]
    nasa_hourly_data = nasa_sort_hourly(nasa_hourly_data_path)
    eccc_title = eccc_data[0]
    eccc_var = find_the_column(eccc_title)
    del eccc_data[0]
    try:
        for count, data in enumerate(eccc_data):
            # first two if determine whether the min and max temp present, if either one of them null or equal to 0,
            # both will be repalced by nasa data
            try:
                if data[(eccc_var['min'])] == '' or data[(eccc_var['min'])] == '0':
                    temp = find_max_min_temp_hourly_nasa_single(nasa_hourly_data, count)
                    t_max = temp['max']
                    t_min = temp['min']
                    eccc_data[count][eccc_var['min']] = t_min
                    eccc_data[count][eccc_var['max']] = t_max
            except Exception as e:
                print(e)
            try:
                if data[eccc_var['max']] == '' or data[eccc_var['max']] == '0':
                    temp = find_max_min_temp_hourly_nasa_single(nasa_hourly_data, count)
                    t_max = temp['max']
                    t_min = temp['min']
                    eccc_data[count][eccc_var['min']] = t_min
                    eccc_data[count][eccc_var['max']] = t_max
            except Exception as e:
                print(e)
            # check rain
            try:
                if data[eccc_var['rain']] == '':
                    eccc_data[count][eccc_var['rain']] = nasa_daily_data[count][6]

                if data[eccc_var['rain']] == '0':
                    if nasa_daily_data[count][6] != 0:
                        eccc_data[count][eccc_var['rain']] = nasa_daily_data[count][6]
            except Exception as e:
                print(e)
            try:
                # check rh
                if data[eccc_var['RH']] == '' or data[eccc_var['RH']] == '0' or data[eccc_var['RH']] == '100':
                    eccc_data[count][eccc_var['RH']] = nasa_daily_data[count][2]
                    # print(data)
            except Exception as e:
                print(e)
            # check wind speed
            try:
                if data[eccc_var['wind']] == '' or data[eccc_var['wind']] == '0':
                    eccc_data[count][eccc_var['wind']] = float(nasa_daily_data[count][4]) * 3.6
            except Exception as e:
                print(e)
            # #check solar
            # if data[6] == '' or data[6] == '0':
            #     eccc_data[count][6] = nasa_daily_data[count][11]
            #
            # check snow
            try:
                if data[eccc_var['snow']] == '' or data[eccc_var['snow']] == '0':
                    eccc_data[count][eccc_var['snow']] = nasa_daily_data[count][8]
            except Exception as e:
                print(e)
            # try:
            #     if not check_RH_val(data, eccc_var['RH']):
            #         eccc_data[count][eccc_var['RH']] = avg_to_fill(count, eccc_data, eccc_var['RH'])
            # except Exception as e:
            #     eccc_data[count][eccc_var['RH']] = 0
            #     print(e)
    except Exception as e:
        print(e)
        # print(data)
    eccc_data.insert(0, eccc_title)
    write_to_to_csv_list_of_lists(name + '.csv', eccc_data)


def read_json(path_name):
    with open(path_name) as f:
        data = json.load(f)
    return data


def nasa_sort_hourly(path):
    # this function is to sort hourly nasa function into a list of lists
    # each list in the big list contains the value for every 24 hour data
    with open(path) as f:
        lines = [line.rstrip('\n') for line in f]
        del lines[0]

    datas = []
    oneday = []
    for count, data in enumerate(lines):
        if count != 0 and (count + 1) % 24 == 0:
            datas.append(oneday)
            oneday = []
        else:
            data = data.split(',')
            oneday.append(data)
    return datas


def write_to_rzwqm_met(name, parsed_content, head):
    to_write = []
    for line in parsed_content:
        s = f"   {line[0]}   {line[1]}   {line[2]}   {line[3]}   {line[4]}   {line[5]}   {line[6]}   {line[7]}   {line[8]}    {line[9]}"
        to_write.append(s)
    head.extend(to_write)
    with open(name, 'w') as file:
        for line in head:
            file.write(line + '\n')


def find_max_min_temp_hourly_nasa_range(path, start, end, create_csv=False):
    datas = nasa_sort_hourly(path)
    res = []
    dif = end - start
    for i in range(dif):
        temp = []
        for val in datas[start]:
            temp.append(val[2])
        t_max = max(temp)
        t_max = float(t_max) - 273.15
        t_min = min(temp)
        t_min = float(t_min) - 273.15
        res.append({'count': start, 'max': t_max, 'min': t_min})
        start = start + 1
    if create_csv:
        with open('maxmin.csv', 'w', encoding='utf8', newline='') as output_file:
            fc = csv.DictWriter(output_file,
                                fieldnames=res[0].keys(),
                                )
            fc.writeheader()
            fc.writerows(res)


def find_max_min_temp_hourly_nasa_single(data, count):
    temp = []
    for val in data[count]:
        temp.append(val[2])
    t_max = max(temp)
    t_max = float(t_max) - 273.15
    t_min = min(temp)
    t_min = float(t_min) - 273.15
    return {'max': t_max, 'min': t_min}


def avg_to_fill(count, data, i):
    val = (float(data[count + 1][i]) + float(data[count - 1][i])) / 2
    return val


def check_RH_val(data, i):
    if float(data[i]) > 100:
        return False
    else:
        return True


def fast_scandir(dirname):
    subfolders = [f.path for f in os.scandir(dirname) if f.is_dir()]
    for dirname in list(subfolders):
        subfolders.extend(fast_scandir(dirname))
    return subfolders


def sort_hourly(data, fmt, header, val_col):
    sorted_data = {}
    var_position = find_the_column(header)
    for count, line in enumerate(data):
        date = datetime.strptime(line[var_position['date']], fmt)
        date_pre = datetime.strptime(data[count - 1][var_position['date']], fmt)
        try:
            if date.day == date_pre.day and count != 0:
                if line[var_position[val_col]] != 'NULL' or line[var_position[val_col]] != '':
                    sorted_data[date.strftime('%Y-%m-%d')].append(float(line[var_position[val_col]]))
            else:
                sorted_data[date.strftime('%Y-%m-%d')] = []
                if line[var_position[val_col]] != 'NULL' or line[var_position[val_col]] != '':
                    sorted_data[date.strftime('%Y-%m-%d')].append(float(line[var_position[val_col]]))
        except Exception as e:
            sorted_data[date.strftime('%Y-%m-%d')].append(0)
            continue

    return sorted_data


def write_dict_to_csv(the_dict, path):
    with open(path, 'w', newline='\n') as result_file:
        writer = csv.writer(result_file)
        for key, value in the_dict.items():
            writer.writerow([key, value])


def handle_data_not_daily_to_daily(data, interval, average=True):
    sorted_list = []
    temp_list = []
    for count, line in enumerate(data):
        val = 0
        if line != 'NaN' or line != '':
            val = float(line)
        if (count + 1) % interval == 0:
            if not average:
                temp_list.append(val)
                no_zero = [n for n in temp_list if n != 0]
                print(no_zero)
                if len(no_zero) > 0:
                    sorted_list.append(no_zero)
                temp_list = []
            else:
                temp_list.append(val)
                no_zero = [n for n in temp_list if n != 0]
                if len(no_zero) > 0:
                    sorted_list.append(round(statistics.mean(no_zero), 2))
                else:
                    sorted_list.append(0)
                temp_list = []
        else:
            temp_list.append(val)
    return sorted_list


def write_met_file_for_a_station(station):
    write_list = []
    duration_for_station = \
        select_one_value_from_a_col_with_condition('simulation period', 'soil_info_for_station', 'Station_id', station)[
            0]
    duration_for_station_split = duration_for_station.split('-')
    start_date = datetime.strptime(duration_for_station_split[0] + '0101', '%Y%m%d')
    end_date = datetime.strptime(duration_for_station_split[-1] + '1231', '%Y%m%d')
    values = select_multiple_col_based_on_date_range(start_date, end_date, station, '`date`, `minimum_air_temp`, '
                                                                                    '`minimum_air_temp_nasa`, '
                                                                                    '`max_air_temp`, '
                                                                                    '`max_air_temp_nasa`, `RH`, '
                                                                                    '`RH_nasa`, `wind_speed`, '
                                                                                    '`wind_speed_nasa`, '
                                                                                    '`solar_radiation`, '
                                                                                    '`solar_radiation_nasa`, '
                                                                                    '`total_rain_adjusted` '
                                                                                    ', `total_rain_nasa`')
    for value in values:
        daily_list = [None] * 10
        date = value[0]
        day = date.strftime('%j')
        year = date.strftime('%Y')
        daily_list[0] = day
        daily_list[1] = year
        minimum_air_temp = value[1]
        minimum_air_temp_nasa = value[2]
        if minimum_air_temp is not None and minimum_air_temp != 0 and minimum_air_temp != 999:
            daily_list[2] = minimum_air_temp
        else:
            daily_list[2] = minimum_air_temp_nasa
        max_air_temp = value[3]
        max_air_temp_nasa = value[4]
        if max_air_temp is not None and max_air_temp != 0 and max_air_temp != 999:
            daily_list[3] = max_air_temp
        else:
            daily_list[3] = max_air_temp_nasa
        RH = value[5]
        RH_nasa = value[6]
        if RH is not None and RH <= 100 and RH != 0 and RH != 999:
            daily_list[7] = RH
        else:
            daily_list[7] = RH_nasa
        wind_speed = value[7]
        wind_speed_nasa = value[8]
        try:
            if wind_speed is not None and wind_speed != 0 and wind_speed != 999:
                daily_list[4] = round(wind_speed * 24, 2)
            else:
                daily_list[4] = round(wind_speed_nasa * 24, 2)
        except Exception as e:
            print(e)

        solar_radiation = value[9]
        solar_radiation_nasa = value[10]
        # cweeds_solar = value[13]
        # cweeds_diffuse_horizontal = value[14]
        # if solar_radiation is not None and solar_radiation != 999 and solar_radiation != 0:
        #     daily_list[5] = solar_radiation
        # elif cweeds_solar is not None and cweeds_solar != 999 and cweeds_solar != 0:
        #     daily_list[5] = cweeds_solar
        # else:
        daily_list[5] = solar_radiation_nasa

        total_rain_adjusted = value[11]
        total_rain_nasa = value[12]
        if total_rain_adjusted is not None and total_rain_adjusted != 0 and total_rain_adjusted != 999:
            if total_rain_nasa is not None:
                # if total_rain_adjusted > total_rain_nasa:
                daily_list[9] = total_rain_adjusted
            # else:
            #     daily_list[9] = total_rain_nasa
            else:
                daily_list[9] = total_rain_adjusted
        else:
            daily_list[9] = total_rain_nasa
        daily_list[8] = 0
        daily_list[6] = 0
        write_list.append(daily_list)

    write_to_rzwqm_met('../met_files/' + station + '.met', write_list)

#
# if __name__ == '__main__':
#     general_path = '../snow_depth_project/project_data/'
#     temp_2021_raw = read_the_file('../tile_drainage_and_p_simulation/soil_temp_st_emm/2022.txt', True)
#     refined_data = {}
#     for count, data in enumerate(temp_2021_raw):
#         date = data[0].replace('"', '')
#         date = date.split()[0]
#         if count < len(temp_2021_raw) - 1:
#             date_next = temp_2021_raw[count + 1][0].replace('"', '')
#             date_next = date_next.split()[0]
#             try:
#                 soil_temp = float(data[6])
#                 if date == date_next and count == 0:
#                     refined_data[date] = []
#                     if soil_temp != "NAN":
#                         refined_data[date].append(soil_temp)
#                 elif date == date_next:
#                     if soil_temp != "NAN":
#                         refined_data[date].append(soil_temp)
#                 elif date != date_next:
#                     if soil_temp != "NAN":
#                         refined_data[date].append(soil_temp)
#                     refined_data[date_next] = []
#             except ValueError as e:
#                 continue
#
#     daily_st = {}
#     for line in refined_data:
#         if len(refined_data[line]) > 0:
#             daily_st[line] = statistics.mean(refined_data[line])
#
#     write_dict_to_csv(daily_st, 'soil_temp_2022_50cm.csv')
#
#     # res = check_missing_day('../ca_freeze_thaw/sorted_met_for_ca_snow_freeze/1016940.csv')
#     # pprint(res)
#     # fill_up_missing_data_using_nasa_data('../snow_depth_project/project_data/lethbridge/lethbridge_ec.csv',
#     #                                      '../snow_depth_project/project_data/lethbridge/nasa_daily.csv',
#     #                                      '../snow_depth_project/project_data/lethbridge/nasa_hourly.csv',
#     #                                      1,
#     #                                      '%d-%b-%y',
#     #                                      'lethbridge_ec_filled_with_nasa')
#     # read_all(path, "breton_ec.csv")
#
#     ###for glenlea
#     # read_all(path, 'glenlea_ec.csv')
#     # fill_up_missing_data_using_nasa_data('../snow_depth_project/project_data/glenlea/glenlea_ec.csv',
#     #                                      '../snow_depth_project/project_data/glenlea/nasa_daily.csv',
#     #                                      '../snow_depth_project/project_data/glenlea/nasa_hourly.csv',
#     #                                      4,
#     #                                      '%Y-%m-%d',
#     #                                      '../snow_depth_project/project_data/glenlea/parsed_ec')
#
#     ###for patty
#     # read_all(path, 'patty_all_ec_2013_to_2020_hourly.csv')
#     # data = read_the_file_split('../snow_depth_project/project_data/patty/patty_all_ec_2013_to_2020_hourly.csv')
#     # del data[0]
#     # RH = [n[13] for n in data]
#     # try:
#     #     RH_avg = handle_data_not_daily_to_daily(RH, 24)
#     # except  ValueError as e:
#     #     pass
#     #
#     # temp = [n[9] for n in data]
#     # sorted_temp = handle_data_not_daily_to_daily(temp, 24, False)
#     # max_temp = [max(n) for n in sorted_temp]
#     # min_temp = [min(n) for n in sorted_temp]
#     # wind = [n[19] for n in data]
#     # wind_sorted = handle_data_not_daily_to_daily(wind, 24)
#     # with open('../snow_depth_project/project_data/patty/patty_hourly_to_daily.csv', 'w') as file:
#     #     for count, val in enumerate(RH_avg):
#     #         file.write(str(val) + ';' + str(max_temp[count]) + ';' + str(min_temp[count]) +';' + str(wind_sorted[count]))
#     #         file.write('\n')
#     #
#     # fill_up_missing_data_using_nasa_data('../snow_depth_project/project_data/patty/patty_all_ec_2013_to_2020.csv',
#     #                                      '../snow_depth_project/project_data/patty/nasa_daily.csv',
#     #                                      '../snow_depth_project/project_data/patty/nasa_hourly.csv',
#     #                                      4,
#     #                                      '%d-%b-%y',
#     #                                      '../snow_depth_project/project_data/patty/parsed_ec.csv')
#
#     # for guelph
#     # fill_up_missing_data_using_nasa_data('../snow_depth_project/project_data/guelph/2006_2018_filled_missing.csv',
#     #                                      '../snow_depth_project/project_data/guelph/1989_2018_daily.csv',
#     #                                      '../snow_depth_project/project_data/guelph/met_nasa_hourly.csv',
#     #                                      0,
#     #                                      '%d/%m/%Y',
#     #                                      '../snow_depth_project/project_data/guelph/snow_final')
#
#     # for oldscollege
#     # fill_up_missing_data_using_nasa_data('../snow_depth_project/project_data/olds_college/oldscollege_ec.csv',
#     #                                      '../snow_depth_project/project_data/olds_college/nasa_daily.csv',
#     #                                      '../snow_depth_project/project_data/olds_college/nasa_hourly.csv',
#     #                                      1,
#     #                                      '%d/%m/%Y',
#     #                                      '../snow_depth_project/project_data/olds_college/parsed_ec')
#
#     ######write all daily env canada file to one file for each station
#     # all_path = fast_scandir('..\\ca_freeze_thaw\\met_data_hourly')
#     # for path in all_path:
#     #     name = path.split('\\')[-1]
#     #     read_all_and_write_to_one(path, '.\\met_data_hourly_to_daily_rh\\'+name + '.csv', 'hourly')
#     ######write met file for ca_freeze_thaw
