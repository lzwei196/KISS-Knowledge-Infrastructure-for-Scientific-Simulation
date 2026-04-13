# the data calibration module's purpose is to examine which of the data has problem, and fill it up with other data sources.
from time import time

from data_handle.direct_env_data_handle import write_to_to_csv_list_of_lists, read_the_file, find_the_column
from db_functions import *
import geopy.distance
from data_download.cygwin_eccc import DL_eccc
from snow_depth_project.snow_depth_db_functions import *
from csv_parsing import read_the_file_split
from datetime import datetime, timedelta

EC_api_date_format = '%Y-%m-%d %H:%M:%S'
nasa_power_date_format = '%Y%m%d'
input_date_format = '%Y-%m-%d'
temp_data_path_daily_head = '../temp_meteo_data_daily'
temp_data_path_hourly_head = '../temp_meteo_data_hourly'
# climate_to_station = climate_id_and_station_id('../StationInventory.csv')

def write_to_rzwqm_met(name, parsed_content, head):
    to_write = []
    for line in parsed_content:
        s = f"   {line[0]}   {line[1]}   {line[2]}   {line[3]}   {line[4]}   {line[5]}   {line[6]}   {line[7]}   {line[8]}    {line[9]}"
        to_write.append(s)
    head.extend(to_write)
    with open(name, 'w') as file:
        for line in head:
            file.write(line + '\n')


def generate_rzwqm_met_header(start_date, end_date):
    begin_year = start_date.strftime('%Y')
    begin_month = start_date.strftime('%m')
    begin_day = start_date.strftime('%d')
    end_year = end_date.strftime('%Y')
    end_month = end_date.strftime('%m')
    end_day = end_date.strftime('%d')
    lines = [
        "===============================================================================",
        "=",
        "=   R   Z   W   Q   M   2",
        "=   User   edited/created   daily   met   file",
        "=",
        "=   daily   METEOROLOGICAL   DATA",
        "=   RECORD   1   GENERAL   INFORMATION",
        "=   ITEM   NO.   DESCRIPTION",
        "=   --------   -----------",
        f"=   1   beginning   calendar   date   of   met   data[{begin_year}   {begin_month}   {begin_day}]",
        f"=   2   ending   calendar   date   of   met   data   [{end_year}   {end_month}   {end_day}]",
        "=   3   indicator   flag   for   daily   (=0)[*.met   file]   or   hourly   (=1)[*.hmt   file]   input",
        "=",
        "=   beginning   Date   ending   Date   Metflag",
        "===============================================================================",
        f"    {begin_year}   {begin_month}   {begin_day}   {end_year}   {end_month}   {end_day}   0",
        "===============================================================================",
        "=   RECORD   2...N   DAILY   DATA",
        "=   ITEM   NO.   DESCRIPTION",
        "=   --------   -----------",
        "=   1   Julian   day   counted   from   Jan   1st[1-365/366]",
        "=   2   year   [YYYY]",
        "=   3   daily   Tmin   [C]",
        "=   4   daily   Tmax   [C]",
        "=   5   daily   wind   run   [km/day]",
        "=   6   daily   sw   rad   [MJ/m^2/day]",
        '=   7   daily   pan   evap   [cm   "H2O/day][optional,default=0]"',
        "=   8   daily   relative   humidity   [0..100]",
        "=   9   daily   photosynthetically   active   radiation   or   photon   flux",
        '=   density   (moles[quanta]/m2/day)[optional   for   "DSSAT,default=0]"',
        '=   10   daily   rainfall   [mm]   [optional   if   wanting   to   create   a   breakpoint   file   from   a   daily   "precip,default=0]]"',
        "=",
        "=   ...repeat   record   for   each   day",
        "=",
        "=   Day   year   Tmin   Tmax   U   Rad   E-pan   RH   PAR   Rain",
        "==============================================================================="
    ]

    return lines

def envrioniment_canada_data_to_db():
    ####environment canada data retrive to database
    table_name = 'environment_canada_station_data'
    station_id_list = read_the_file_o('../StationInventory.csv', True, ',')
    station_id_list = station_id_list[3:]
    station_id_list = [x[2] for x in station_id_list]
    for station_id in station_id_list:
        try:
            res = \
                select_one_value_from_a_col_with_condition_in_schema('ec_data', 'environment_canada_station_data',
                                                                     'station_id', station_id)[0]
            if res is None:
                ec = ec_met_data_retrieve(str(station_id))
                ec.ec_daily_and_hourly_met_data_retrieve()
                print(f'{station_id} finshed')
            else:
                print('skipping {}, data exists'.format(station_id))
                continue
        except Exception as e:
            print(e)
            continue


def closest_value(my_list, target):
    """
    Find the element in my_list that is closest to the target value.

    Parameters:
        my_list (list): The list of numbers to search through.
        target (float): The target value to find the closest element to.

    Returns:
        float: The closest element to the target value in my_list.
    """
    if not my_list:
        return None  # Return None if the list is empty

    closest = my_list[0]  # Initialize closest value to the first element in the list
    min_diff = abs(target - closest)  # Initialize minimum difference

    for value in my_list[1:]:  # Skip the first element as it's already considered
        diff = abs(target - value)  # Calculate absolute difference
        if diff < min_diff:  # Update closest and min_diff if a closer value is found
            closest = value
            min_diff = diff

    return closest


def file_name_and_path_in_dir(path, file_format):
    # file format .txt or .csv
    path_to_data_folder = path
    all_path = {}
    for file in os.listdir(path_to_data_folder):
        if file.endswith(file_format):
            the_path = os.path.join(path, file)
            file_name = (the_path.split('/')[-1]).split('.')[0]
            # file_name = file_name.split('\\')[1]
            all_path[file_name] = the_path

    return all_path


def check_missing_day_and_fill_with_placeholder(ec_data, columns, fmt='%Y-%m-%d'):
    # the function takes in the environment canada data and check whether there are missed dates
    # fmt = '%d/%m/%Y'
    days = 0
    title = ec_data[0]
    del ec_data[0]
    # all the lines has been splited into list of lists.
    for count, splitted_data in enumerate(ec_data):
        try:
            date_current = datetime.strptime((ec_data[count])[columns['date']], fmt)
            date_next = datetime.strptime((ec_data[count + 1])[columns['date']], fmt)
            days = (date_next - date_current).days
        except Exception as e:
            print(e)
            print('ending touched')
            pass
        if days > 1:
            print(days)
            print(f"Missing date at {date_current}")
            num = count
            for i in range(days - 1):
                date_current = date_current + timedelta(days=1)
                ec_data.insert(num + 1, [str(date_current.strftime(fmt))])
                num = num + 1
    # push the first line back in
    ec_data.insert(0, title)

    return ec_data


def check_for_none_in_tuples(tuple_list):
    for i, t in enumerate(tuple_list):
        for j, element in enumerate(t):
            if element is None:
                return True
    return False


def return_none_indices(tuple_list):
    none_indices = []
    for i, t in enumerate(tuple_list):
        for j, element in enumerate(t):
            if element is None:
                none_indices.append((i, j))
    return none_indices


def check_values(tuple_list):
    indices = []


    for i, t in enumerate(tuple_list):

        # Check for -99, None, or empty string
        for j, element in enumerate(t):
            if element in (-99, None, '', -7999.00, '-7999.00'):
                indices.append((i, j))
        if t[6] is not None:
            indices.append((i, 6))
        # Check if tuple[2] > tuple[1]
        try:
            if t[1] > t[2]:
                indices.append((i, 1))
                indices.append((i, 2))

            # Check if tuple[5] >= 100
            if t[5] >= 100:
                indices.append((i, 5))
        except Exception as e:
            continue

    return indices


def parse_adjusted_temperature_data(data):
    # Initialize an empty dictionary to store the parsed data
    parsed_data = {}

    # Split the data into lines
    lines = read_the_file_o(data, False)

    # Skip the header lines (assuming 4 header lines)
    for line in lines[4:]:
        # Extract the year and month from the first two columns
        year = int(line[:5].strip())
        month = int(line[5:8].strip())

        # Initialize start index for daily data
        start_idx = 8

        # Loop through the remaining columns to get the daily data
        for day in range(1, 32):
            # Extract temperature string based on fixed width
            temp_str = line[start_idx:start_idx + 8].strip()

            # Remove any trailing alphabets
            temp_str = re.sub('[a-zA-Z]', '', temp_str)

            # Check if the temperature is an error value
            if temp_str in ['-9999.9', '-9999.9', '-9999.9M', '-9999.9e']:
                temp = None
            else:
                try:
                    temp = float(temp_str)
                except ValueError:
                    temp = None

            # Create a datetime object for the day
            try:
                date = datetime(year, month, day)

                # Add the data to the dictionary
                parsed_data[date] = temp
            except ValueError:
                # ValueError will be raised by datetime for invalid day (e.g., Feb 31)
                pass

            # Move to next column
            start_idx += 8

    return parsed_data


# the function takes in a ec data and return a dict of {day:{env_variable:...}}
def env_data_to_dict(columns, ec_data):
    env_data_dict = {}
    del ec_data[0]
    date_str = ec_data[0][columns['date']]
    date_format = find_date_format(date_str)
    # delete header
    for each_line in ec_data:
        try:
            env_data_dict[datetime.strptime(each_line[columns['date']], date_format)] = {x: each_line[v] for x, v in
                                                                                         columns.items()}
        except Exception as e:
            continue
    return env_data_dict


class Manitoba_data_retrieve:
    def __init__(self, station_id, start, end, lat, lon, data_fill_range=200):
        self.station_id = station_id
        self.start = datetime.strptime(start, input_date_format)
        self.end = datetime.strptime(end, input_date_format)
        self.lat = lat
        self.lon = lon
        self.data_fill_range = data_fill_range

    @property
    def return_start_and_end(self):
        station_dates = return_start_and_end_each_station(self.station_id)
        return station_dates[0][1], station_dates[0][0]

    @property
    def return_lat_lon_for_the_station(self):
        lat_and_long = return_lat_and_lon_for_station(self.station_id)
        return lat_and_long[0], lat_and_long[1]

    def return_manitoba_env_data(self):
        data = query_duration_met_input(self.station_id)
        return data

    def check_date_completeness(self):

        date_dict = {datetime.combine(date_tuple[0], time()): date_tuple for date_tuple in
                     self.return_manitoba_env_data()}

        # Generate all expected dates between start and end date
        expected_dates = [self.start + timedelta(days=i) for i in
                          range((self.end - self.start).days + 1)]
        position = (len(self.return_manitoba_env_data()[0]) - 1)
        # Insert missing dates
        for date in expected_dates:
            if date not in date_dict:
                # Prepare a tuple with 'None' values for missing dates
                placeholder_tuple = (date,) + (None,) * position
                date_dict[date] = placeholder_tuple

        # Sort and convert back to list of tuples
        updated_list = [date_dict[date] for date in sorted(date_dict.keys())]

        return updated_list

class Data_Calibration:
    def __init__(self, simulate_path, observed_path, station_id, province):
        self.simulate_path = simulate_path
        self.observed_path = observed_path
        self.station_id = station_id
        self.province = province

    @staticmethod
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

    def return_potential_station_list(self, s_range):
        altitude_column = 5
        longitude_column = 6
        current_station = select_general_station_id('station_id', self.station_id)
        current_station_cords = (current_station[0][altitude_column], current_station[0][longitude_column])
        result = select_general_station_id('province', self.province)
        result_list = []
        for res in result:
            cord = (res[5], res[6])
            dis = geopy.distance.geodesic(current_station_cords, cord).km
            if dis <= s_range:
                if self.station_id != res[4]:
                    result_list.append({'station_id': res[4], 'distance_dif': dis})
        # sort the list based on the distance from the station to the current station
        result_list.sort(key=lambda x: x['distance_dif'])
        return result_list



    def check_over_value(self, threshold, simulate_data, condition, write_to_file=False):
        observed_lines = read_the_file(self.observed_path)
        head = observed_lines[0]
        del observed_lines[0]
        return_array = []
        try:
            for count, line in enumerate(observed_lines):
                observed = float(line[1])
                simulated = float(simulate_data[count])
                #dif = self.get_change(simulated, observed)
                dif = self.check_the_differance_snow(simulated, observed, condition)
                print(dif, line[0])
                if dif > threshold:
                    return_array.append(
                        {'count': count, 'date': line[0], 'dif': dif, 'simulated': simulated, 'observed': observed})
        except IndexError as e:
            print(e)

        return_array.insert(0, head)
        if write_to_file:
            write_to_to_csv_list_of_lists('data_needed_modification.csv', return_array)

        return return_array

    def download_one_year_data(self, year, station_id):
        db_has_year = select_dl_eccc_data(year, station_id)
        if not db_has_year:
            try:
                dl = DL_eccc()
                file = dl.download_data(station_id, year)
                add_downloaded_data(file.strip('../data/'), file, station_id, year)
                return file
            except Exception as e:
                print(e)
        else:
            return db_has_year[0]

    def find_max_among_stations(self, station_list, year, date_needs_change):
        rain_list = []
        for station in station_list:
            station_has_year = self.check_if_station_has_the_year(station['station_id'], year)
            if station_has_year:
                file = self.download_one_year_data(year, station['station_id'])
                data_lines = read_the_file_split(file)
                columns = find_the_column(data_lines[0])
                del data_lines[0]
                for row in data_lines:
                    the_date = datetime.strptime(row[columns['date']], ('%Y-%m-%d'))
                    if the_date.date() == date_needs_change.date():
                        if row[columns['rain']]:
                            rain = float(row[columns['rain']])
                            rain_list.append(rain)
                            break
        if len(rain_list) >0:
            return max(rain_list)

    def fill_up_data_from_nearby_station(self, s_range, threshold, simulate_data):
        data_list = self.check_over_value(threshold, simulate_data)
        del data_list[0]

        station_list = self.return_potential_station_list(s_range)
        print(station_list)
        completed = []
        incomplete = []
        try:
            for data in data_list:
                count = data['count']
                date_needs_change = datetime.strptime(data['date'], ('%Y-%m-%d'))
                year = date_needs_change.year
                rain = ''
                # for station in station_list:
                #     station_has_year = self.check_if_station_has_the_year(station['station_id'], year)
                #     if station_has_year:
                #         file = self.download_one_year_data(year, station['station_id'])
                #         data_lines = read_the_file_split(file)
                #         columns = find_the_column(data_lines[0])
                #         del data_lines[0]
                #         for row in data_lines:
                #             the_date = datetime.strptime(row[columns['date']], ('%Y-%m-%d'))
                #             if the_date.date() == date_needs_change.date():
                #                 rain = row[columns['rain']]
                rain = self.find_max_among_stations(station_list, year, date_needs_change)
                if rain or rain == 0:
                    completed.append({'date': date_needs_change, 'new_value': rain, 'count': count})
                    # break
                # if rain:
                #     break
                if not rain and rain != 0:
                    print(f"the current range of station doesn't contain enough data for {date_needs_change}")
                    incomplete.append(data)
            if len(incomplete) == 0:
                print('All data has been fulfilled')
                print(completed)
                return completed
            elif len(incomplete) > 0:
                print(completed)
                # print('Following data are unable to autotill due to insufficient data \n')
                # print(incomplete)
                return completed
        except Exception as e:
            print(e)

    @staticmethod
    def check_if_station_has_the_year(station_id, year):
        years = select_the_station_year_dly(station_id)
        try:
            if years[0] and years[1]:
                if year == years[0] or year == years[1]:
                    return True
                else:
                    is_between = year in range(years[0], years[1])
                return is_between
            else:
                return False
        except Exception as e:
            print(e)

    @staticmethod
    def get_change(simulate, observed):
        if simulate == observed:
            return 100.0
        elif observed > 0 and simulate == 0:
            return 101.0
        try:
            return (abs(simulate - observed) / observed) * 100.0
        # if the observed is
        except ZeroDivisionError:
            if simulate > 0:
                return 101
            else:
                return 100

    @staticmethod
    def check_the_differance_snow(simulate, observed, condition):
        if condition == 'less':
            if simulate < observed:
                if simulate == observed:
                    return 0
                elif observed == 0:
                    return 0
                elif simulate == 0:
                    return 100
                return (abs(simulate - observed) / observed) * 100.0
            else:
                return 0
        elif condition == 'over':
            if simulate > observed:
                if simulate == observed:
                    return 0
                elif observed == 0 or simulate == 0:
                    return 0
                return (abs(simulate - observed) / observed) * 100.0
            else:
                return 0

# simulated_data = dc.rzwqm_res_parse('snow')
# res = dc.check_over_value(100, simulated_data)
# print(res)
