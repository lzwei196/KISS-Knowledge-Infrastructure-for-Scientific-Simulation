import csv
import os
import statistics
from datetime import datetime, timedelta
from csv_parsing import read_the_file_split


def read_text_file(path):
    with open(path) as f:
        lines = [line.rstrip('\n') for line in f]
    parsed_data_all = []
    for line in lines:
        # print(line)
        split_line = line.split()
        parsed_data_all.append(split_line)
    # print(parsed_data_all)
    return parsed_data_all

def loop_between_dates(start_date, end_date, increment_days=1):
    """
    Loop between two datetime objects with a specified increment in days.

    Parameters:
    - start_date: The start datetime object
    - end_date: The end datetime object
    - increment_days: The number of days to increment in each loop (default is 1)

    Returns:
    - A list of datetime objects between the start and end dates with the specified increment
    """
    current_date = start_date
    date_list = []

    while current_date <= end_date:
        date_list.append(current_date)
        current_date += timedelta(days=increment_days)

    return date_list

def write_to_to_csv_list_of_lists(path, s):
    with open(path, "w", newline="", encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(s)

def read_the_file_o(path, split_boo, split_delimiter=';'):
    with open(path, encoding="utf-8-sig", errors='ignore') as f:
        lines = [line.rstrip('\n') for line in f]
    parsed_data_all = []
    for data in lines:
        if split_boo:
            parsed_data = data.split(split_delimiter)
            parsed_data_all.append(parsed_data)
        else:
            parsed_data_all.append(data)

    return parsed_data_all


def read_the_file(path):
    with open(path, encoding="utf8", errors='ignore') as f:
        lines = [line.rstrip('\n') for line in f]
    parsed_data_all = []
    for data in lines:
        parsed_data = data.split(',')
        parsed_data_all.append(parsed_data)
    return parsed_data_all


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


class find_the_index:
    def __init__(self, s):
        self.s = s

    def find_min_temp(self):
        if self.s == 'MIN_TEMPERATURE':
            return True
        elif self.s == 'Min Temp (°C)':
            return True
        elif self.s == 'Air Temp. Min.':
            return True
        elif self.s == 'Air Temp. Min. (°C)':
            return True
        elif self.s == 'min_temp':
            return True
        elif self.s == 'min':
            return True
        elif self.s =='MinAir_T':
            return True

    def find_max_temp(self):
        if self.s == 'MAX_TEMPERATURE':
            return True
        elif self.s == 'Max Temp (°C)':
            return True
        elif self.s == 'Air Temp. Max.':
            return True
        elif self.s == 'Air Temp. Max. (°C)':
            return True
        elif self.s == 'max_temp':
            return True
        elif self.s == 'max':
            return True
        elif self.s =='MaxAir_T':
            return True

    def find_rain(self):
        if self.s == 'TOTAL_PRECIPITATION':
            return True
        elif self.s == 'Total Precip (mm)':
            return True
        elif self.s == 'Precip. (mm)':
            return True
        elif self.s == 'total_rain':
            return True
        elif self.s == 'Rainfall':
            return True

    def find_snow(self):
        if self.s == 'SNOW_ON_GROUND':
            return True
        elif self.s == 'Snow on Grnd (cm)':
            return True
        elif self.s == 'Total Snow (cm)':
            return True
        elif self.s == 'Snow Depth (cm)':
            return True
        elif self.s == 'Snow depth':
            return True

    def find_RH(self):
        if self.s == 'RH_avg':
            return True
        elif self.s == 'Humidity Avg. (%)':
            return True
        elif self.s == 'RH':
            return True
        elif self.s == 'Rel Hum (%)':
            return True
        elif self.s == 'Relative Humidity':
            return True
        elif self.s == 'AvgRH':
            return True

    def find_date(self):
        if self.s == 'Date/Time':
            return True
        elif self.s == 'Date (Local Standard Time)':
            return True
        elif self.s == 'Date/Time (LST)':
            return True
        elif self.s == '# Date':
            return True
        elif self.s == 'TMSTAMP':
            return True

    def find_solar(self):
        if self.s == 'Incoming Solar Rad. (W/m2)':
            return True
        elif self.s == 'Short-wave irradiation':
            return True

    def find_wind(self):
        if self.s == 'Wind Speed 2 m Avg. (km/h)':
            return True
        elif self.s == 'wind':
            return True
        elif self.s == 'Wind Spd (km/h)':
            return True
        elif self.s == 'Wind speed':
            return True

    def find_temp(self):
        if self.s == 'Temperature':
            return True

    def find_snowfall(self):
        if self.s == 'Snowfall':
            return True


def read_file_path_in_dir_custom(path, extension):
    path_to_data_folder = path
    all_path = []
    for file in os.listdir(path_to_data_folder):
        if file.endswith(extension):
            # the_path = os.path.join(path, file)
            all_path.append(file)
    return all_path


def name_to_date(path, dailyorhourly='daily'):
    name = path.split('_')
    # 6th in the list is the date
    if dailyorhourly == 'hourly':
        date = datetime.strptime(name[5], '%d-%Y')
    elif dailyorhourly == 'daily':
        date = datetime.strptime(name[5], '%Y')
    return date


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


def write_list_to_csv(data_list, file_path):
    """
    Write a list to a CSV file. The list will be written as a single column.

    Parameters:
    - data_list: The list of data to write to the CSV file
    - file_path: The path of the CSV file to write to
    """
    with open(file_path, mode='w', newline='') as file:
        writer = csv.writer(file)
        for item in data_list:
            writer.writerow([item])

def read_all_and_write_to_one_ec_data(path, write_to_name, dailyorhourly, date_format, variable_name=None):
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
            if variable_name == "RH":
                data = sort_hourly(data, '%Y-%m-%d %H:%M', header, variable_name)
                data = [[x, round(statistics.mean(data[x]), 2)] for x in data]
            elif variable_name == "wind":
                data = sort_hourly(data, '%Y-%m-%d %H:%M', header, variable_name)
                data = [[x, sum(data[x])] for x in data]
        all_data.append({'the_date': the_date, 'data': data})

    # sort the data based on date
    all_data.sort(key=lambda x: x['the_date'])

    # add header, the first line
    all_data[0]['data'].insert(0, header)
    for val in all_data:
        write_to_to_csv_list_of_lists('../' +write_to_name, val['data'])

    if dailyorhourly == 'daily':
        return_data = []
        for data in all_data:
            for line in data['data']:
                return_data.append(line)
        return return_data
    elif dailyorhourly == 'hourly':
        return_data = {}
        del all_data[0]['data'][0]
        for data in all_data:
            for line in data['data']:
                return_data[datetime.strptime(line[0], date_format)] = line[1]
        return return_data

def climate_id_and_station_id(cpath):
    station_climate = {}
    with open(cpath) as f:
        csv_reader = list(csv.reader(f, delimiter=','))
        csv_reader = csv_reader[3:]
        for row in csv_reader:
            station_climate[row[2]] = row[3]
    return station_climate