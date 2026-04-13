# from writing_and_reading_functions import read_text_file, write_list_to_csv
# from datetime import datetime, timedelta
# import os
#
# soil_hydraulic_properties_identifier = {
#     'head': '= . . . Repeat for each horizon',
#     'end': '=        SOIL HORIZON HEAT MODEL PARAMETERS'
# }
#
# albedo_identifier = {
#     'head': '=    21      Maxiumum Crop Coefficient                         [0.0-1.3]',
#     'end': '==                 S U R F A C E   R E S I D U E                      =='
# }
#
# snow_identifier = {
#     'head': '=   1.5    PRECIP ALL SNOW IF MAX TEMPERATURE BELOW THIS VALUE [F]',
#     'end': '=     ALBEDO ADJUSTMENTS'
# }
#
# soil_physical_identifer = {
#     'head': '=      ...repeated for each horizon',
#     'end': '==        NUMERICAL SYSTEM CONFIGURATION                              =='
# }
#
# soil_physical_properties_identifer = {
#     'head': '= . . . Repeat for each horizon, soil surface to profile bottom',
#     'end': '=        SOIL HORIZON HYDRAULIC PROPERTIES'
# }
#
# soil_node_identifier = {
#     'head': '=       record (depth increasing with node no.)',
#     'end': '=         SOIL HORIZON PHYSICAL PROPERTIES'
# }
#
# # this is the class the python file describing the different properties for the rz setup
#
# def find_desired_line_numbers(head_identifier, end_identifier, the_file, lines_from_identifer_head_to_increase,
#                               lines_from_identifier_end_to_decrease):
#     first_line_num = 0
#     end_line_num = 0
#     for count, line in enumerate(the_file):
#         if line == head_identifier:
#             first_line_num = count + lines_from_identifer_head_to_increase
#         elif line == end_identifier:
#             end_line_num = count - lines_from_identifier_end_to_decrease
#     return first_line_num, end_line_num
#
#
# def loop_between_dates(start_date, end_date, increment_days=1):
#     """
#     Loop between two datetime objects with a specified increment in days.
#
#     Parameters:
#     - start_date: The start datetime object
#     - end_date: The end datetime object
#     - increment_days: The number of days to increment in each loop (default is 1)
#
#     Returns:
#     - A list of datetime objects between the start and end dates with the specified increment
#     """
#     current_date = start_date
#     date_list = []
#
#     while current_date <= end_date:
#         date_list.append(current_date)
#         current_date += timedelta(days=increment_days)
#
#     return date_list
#
# def generate_rzwqm_met_header(start_date, end_date):
#     begin_year = start_date.strftime('%Y')
#     begin_month = start_date.strftime('%m')
#     begin_day = start_date.strftime('%d')
#     end_year = end_date.strftime('%Y')
#     end_month = end_date.strftime('%m')
#     end_day = end_date.strftime('%d')
#     lines = [
#         "===============================================================================",
#         "=",
#         "=   R   Z   W   Q   M   2",
#         "=   User   edited/created   daily   met   file",
#         "=",
#         "=   daily   METEOROLOGICAL   DATA",
#         "=   RECORD   1   GENERAL   INFORMATION",
#         "=   ITEM   NO.   DESCRIPTION",
#         "=   --------   -----------",
#         f"=   1   beginning   calendar   date   of   met   data[{begin_year}   {begin_month}   {begin_day}]",
#         f"=   2   ending   calendar   date   of   met   data   [{end_year}   {end_month}   {end_day}]",
#         "=   3   indicator   flag   for   daily   (=0)[*.met   file]   or   hourly   (=1)[*.hmt   file]   input",
#         "=",
#         "=   beginning   Date   ending   Date   Metflag",
#         "===============================================================================",
#         f"    {begin_year}   {begin_month}   {begin_day}   {end_year}   {end_month}   {end_day}   0",
#         "===============================================================================",
#         "=   RECORD   2...N   DAILY   DATA",
#         "=   ITEM   NO.   DESCRIPTION",
#         "=   --------   -----------",
#         "=   1   Julian   day   counted   from   Jan   1st[1-365/366]",
#         "=   2   year   [YYYY]",
#         "=   3   daily   Tmin   [C]",
#         "=   4   daily   Tmax   [C]",
#         "=   5   daily   wind   run   [km/day]",
#         "=   6   daily   sw   rad   [MJ/m^2/day]",
#         '=   7   daily   pan   evap   [cm   "H2O/day][optional,default=0]"',
#         "=   8   daily   relative   humidity   [0..100]",
#         "=   9   daily   photosynthetically   active   radiation   or   photon   flux",
#         '=   density   (moles[quanta]/m2/day)[optional   for   "DSSAT,default=0]"',
#         '=   10   daily   rainfall   [mm]   [optional   if   wanting   to   create   a   breakpoint   file   from   a   daily   "precip,default=0]]"',
#         "=",
#         "=   ...repeat   record   for   each   day",
#         "=",
#         "=   Day   year   Tmin   Tmax   U   Rad   E-pan   RH   PAR   Rain",
#         "==============================================================================="
#     ]
#
#     return lines
#
# # class pet_attribute: def __init__(self, dry_soil_albedo, wet_soil_albedo, albedo_of_crop_at_maturity,
# # albedo_of_fresh_residue, heighet_at_wind_measurement_were_taken, average_sunshine_frac, pann_coff,
# # using_hourly_weather, using_shaw, using_penflux, surface_soil_resistance, plant_stress_mode,
# # plastic_mulch_cover_fraction, emissivity_of_canopy, emissivity_of_residue, emissivity_of_snow, emissivity_of_soil,
# # emissivity_of_plastic, pet_calculation_method, initial_crop_coff, maximum_crop_coff):
# #
#
# class soil_hydraulic_properties_each_horizon:
#     def __init__(self, pore_size_dist, saturated_water_content,
#                  residual_water_content, bubbling_pressure, constant_for_oh, lateral_ksat, ksat, eps,
#                  second_intercept_c2, horizon_num):
#         self.bubbling_pressure = bubbling_pressure
#         self.pore_size_dist = pore_size_dist
#         self.saturated_water_content = saturated_water_content
#         self.residual_water_content = residual_water_content
#         self.constant_for_oh = constant_for_oh
#         self.lateral_ksat = lateral_ksat
#         self.ksat = ksat
#         self.eps = eps
#         self.second_intercept_c2 = second_intercept_c2
#         self.horizon_num = horizon_num
#
#     @property
#     def fc33(self):
#         B1 = (
#                      self.saturated_water_content - self.residual_water_content - self.constant_for_oh * abs(
#                  self.bubbling_pressure)) \
#              * abs(self.bubbling_pressure) ** self.pore_size_dist
#         fc33 = B1 / (333 ** self.pore_size_dist) + self.residual_water_content
#         return round(fc33, 2)
#
#     @property
#     def fc10(self):
#         B1 = (
#                      self.saturated_water_content - self.residual_water_content - self.constant_for_oh * abs(
#                  self.bubbling_pressure)) \
#              * abs(self.bubbling_pressure) ** self.pore_size_dist
#         fc10 = B1 / (100 ** self.pore_size_dist) + self.residual_water_content
#         return round(fc10, 2)
#
#     @property
#     def fc15(self):
#         B1 = (
#                      self.saturated_water_content - self.residual_water_content - self.constant_for_oh * abs(
#                  self.bubbling_pressure)) \
#              * abs(self.bubbling_pressure) ** self.pore_size_dist
#         # 15000 is head of wilting point, assuing that 15 bar is the wilting point
#         fc15 = B1 / (15000 ** self.pore_size_dist) + self.residual_water_content
#         return round(fc15, 2)
#
#
# def write_to_rzwqm_met(name, parsed_content, head):
#     to_write = []
#     for line in parsed_content:
#         s = f"   {line[0]}   {line[1]}   {line[2]}   {line[3]}   {line[4]}   {line[5]}   {line[6]}   {line[7]}   {line[8]}    {line[9]}"
#         to_write.append(s)
#     head.extend(to_write)
#     with open(name, 'w') as file:
#         for line in head:
#             file.write(line + '\n')
#
#
# class RZWQM:
#     @property
#     def sno_path(self):
#         return self._sno_path
#
#     def __init__(self, project_path, station):
#         self.station = station
#         self.met_path = project_path + "/Meteorology/" + station + '.met'
#         self.sno_path = project_path + "/Meteorology/" + station + '.sno'
#         self.rzwqm_project_path = project_path
#         self.simulate_path = project_path + '/Analysis/' + station + '.ana'
#         self.dat_path = project_path + station + '/RZWQM.dat'
#         self.init_path = project_path + station + '/RZINIT.dat'
#         self.ipnames_path = project_path + station + '/ipnames.dat'
#         self.kf_path = project_path + station + '/KF.txt'
#         self.soil_ht_path = project_path + station + '/soil_ht_f.txt'
#         self.soil_tk_path = project_path + station + '/soil_tk_f.txt'
#
#     @property
#     def dat_data(self):
#         with open(self.dat_path, encoding="ISO-8859-1") as f:
#             lines = [line.rstrip('\n') for line in f]
#         return lines
#
#     @property
#     def layer_data(self):
#         with open(self.rzwqm_project_path + self.station + '/Layer.plt', encoding="ISO-8859-1") as f:
#             lines = [line.rstrip('\n') for line in f]
#         return lines
#
#     @property
#     def ipnames(self):
#         with open(self.ipnames_path, encoding="ISO-8859-1") as f:
#             lines = [line.rstrip('\n') for line in f]
#         return lines
#
#     @property
#     def met_data(self):
#         with open(self.met_path, encoding="ISO-8859-1") as f:
#             lines = [line.rstrip('\n') for line in f]
#         return lines
#
#     @property
#     def sno_data(self):
#         with open(self.sno_path, encoding="ISO-8859-1") as f:
#             lines = [line.rstrip('\n') for line in f]
#         return lines
#
#     @property
#     def scenario_start_end_date(self):
#         date_line = self.ipnames[8]
#         date_line = date_line.split()
#         starting_date = datetime.strptime(date_line[0] +'/' + date_line[1] + '/' + date_line[2], '%d/%m/%Y')
#         ending_date = datetime.strptime(date_line[3] +  '/' + date_line[4]  +'/' + date_line[5], '%d/%m/%Y')
#         return starting_date, ending_date
#
#     # returns the hydraulic properties for each horzion based on the rzwqm.dat file inputted
#     def return_the_soil_properties_class(self):
#         head_num, end_num = self.line_number_of_soil_hydraulic()
#         dict_with_properties = {}
#         soil_property_for_one_horizon = []
#         for count, line in enumerate(self.dat_data[head_num:end_num + 1]):
#             try:
#                 # every three lines is a horizon
#                 if (count + 1) % 3 == 0:
#                     soil_property_for_one_horizon.append(line.split())
#                     horizon_num = int(soil_property_for_one_horizon[0][0])
#                     bubbling_pressure = round(float(soil_property_for_one_horizon[0][1]), 4)
#                     pore_size_dist = round(float(soil_property_for_one_horizon[0][2]), 2)
#                     eps = round(float(soil_property_for_one_horizon[0][3]), 2)
#                     ksat = round(float(soil_property_for_one_horizon[0][4]), 2)
#                     wr = round(float(soil_property_for_one_horizon[0][5]), 2)
#                     ws = round(float(soil_property_for_one_horizon[0][6]), 6)
#                     second_intercept_c2 = round(float(soil_property_for_one_horizon[1][4]), 2)
#                     lateral_ksat = round(float(soil_property_for_one_horizon[2][0]), 2)
#                     hydraulic_horizon = soil_hydraulic_properties_each_horizon(
#                         pore_size_dist, ws, wr, bubbling_pressure, 0, lateral_ksat, ksat, eps, second_intercept_c2,
#                         horizon_num
#                     )
#                     dict_with_properties[horizon_num] = hydraulic_horizon
#                     soil_property_for_one_horizon = []
#                 else:
#                     soil_property_for_one_horizon.append(line.split())
#             except TypeError:
#                 print(count)
#         return dict_with_properties
#
#     def return_number_of_soil_horizons(self):
#         head_num, end_num = self.line_of_soil_physical_depth()
#         number_of_horizons = int(self.dat_data[head_num][0].split()[0])
#
#         return number_of_horizons
#
#     def return_soil_layer_depth_dict(self):
#         head_num, end_num = self.line_of_soil_physical_depth()
#         number_of_horizons = int(self.dat_data[head_num][0].split()[0])
#         soil_layer_dict = {}
#         for layer_num in range(1, number_of_horizons + 1):
#             line_data = self.dat_data[head_num + layer_num]
#             soil_layer_dict[layer_num] = float(line_data.strip())
#         return soil_layer_dict
#
#     # change the hydraulic properties and write back to the dat file
#     def write_new_hydraulic_properties_to_dat(self, dict_of_soil_properties):
#         head_num, end_num = self.line_number_of_soil_hydraulic()
#         modified_dat = self.dat_data
#         length_from_dat = end_num - head_num
#
#         # if len(dict_of_soil_properties) * 3 - 1 != length_from_dat:
#         #     print('things went wrong when adjusting the calibration input')
#         #
#         # else:
#         for key in dict_of_soil_properties:
#                 property = dict_of_soil_properties[key]
#                 key = key - 1
#                 changing_line_first = str(property.horizon_num) + '  ' + str(property.bubbling_pressure) + '  ' + str(
#                     property.pore_size_dist) + '  ' + str(property.eps) + '  ' + str(property.ksat) + '  ' + str(
#                     property.residual_water_content) + '  ' + str(property.saturated_water_content)
#
#                 changing_line_second = str(property.fc33) + '  ' + str(property.fc10) + '  ' + str(
#                     property.fc15) + '  ' + str(property.bubbling_pressure) + '  ' + str(
#                     property.second_intercept_c2) + '  0  0'
#
#                 changing_line_third = str(property.lateral_ksat)
#
#                 modified_dat[int(head_num) + key * 3] = changing_line_first
#                 modified_dat[int(head_num) + key * 3 + 1] = changing_line_second
#                 modified_dat[int(head_num) + key * 3 + 2] = changing_line_third
#
#         with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
#             for line in modified_dat:
#                 file.write(line + '\n')
#
#     @staticmethod
#     def env_prop(line_num, dat_data):
#         # albedo sector only contains one line of data
#         # this function parses the environmental properties of the dat file
#         dict_with_properties = {}
#         traits = dat_data[line_num].split()
#         dict_with_properties['dry soil albedo'] = traits[0]
#         dict_with_properties['wet soil albedo'] = traits[1]
#         dict_with_properties['albedo of the crop at maturity'] = traits[2]
#         dict_with_properties['albedo of fresh residue'] = traits[3]
#         dict_with_properties['height at which wind measurements are take'] = traits[4]
#         dict_with_properties['average sunshine fraction for a day'] = traits[5]
#         dict_with_properties['PAN COEFFICIENT'] = traits[6]
#         dict_with_properties['Using Hourly weather'] = traits[7]
#         dict_with_properties['SHAW'] = traits[8]
#         dict_with_properties['Penflux'] = traits[9]
#         dict_with_properties['surface soil resistance'] = traits[10]
#         dict_with_properties['stress method'] = traits[11]
#         dict_with_properties['plastic mulch cover fraction'] = traits[12]
#         dict_with_properties['emissivity of canopy'] = traits[13]
#         dict_with_properties['emissivity of residue'] = traits[14]
#         dict_with_properties['emissivity of snow'] = traits[15]
#         dict_with_properties['emissivity of soil'] = traits[16]
#         dict_with_properties['emissivity of plastic'] = traits[17]
#         dict_with_properties['PET calculation method'] = traits[18]
#         dict_with_properties['Initial Crop Coefficient'] = traits[19]
#         dict_with_properties['Maxiumum Crop Coefficient'] = traits[20]
#         dict_with_properties['Albedo of plastic'] = traits[21]
#         dict_with_properties['Transmissivity of plastic'] = traits[22]
#         return dict_with_properties
#
#     def write_env_pop_to_dat(self, modified_properties, dat_data, line_num):
#         # the function write the edited environmental properties to the dat file there is only one line describing
#         # the environmental properties, thus both end line number and start line number can be used
#         modified_dat = dat_data
#         modified_list = list(modified_properties.values())
#         new_str = ''
#         for count, val in enumerate(modified_list):
#             if count != len(modified_list):
#                 new_str = new_str + str(val) + '  '
#             else:
#                 new_str = new_str + str(val)
#         dat_data[line_num] = new_str
#         with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
#             for line in modified_dat:
#                 file.write(line + '\n')
#
#     def write_new_kf(self, new_value):
#         with open(self.kf_path, 'w') as file:
#             for item in new_value:
#                 file.write(f"{item}\n")
#
#     def write_new_soil_tk_f(self, horizon_dict_with_value):
#         new_value_to_write = []
#         soil_dict_nodes = self.return_soil_nodes()
#         for horizon in horizon_dict_with_value:
#             for node in soil_dict_nodes[horizon]:
#                 new_value_to_write.append(horizon_dict_with_value[horizon])
#         with open(self.soil_tk_path, 'w') as file:
#             for item in new_value_to_write:
#                 file.write(f"{item}\n")
#
#     def write_new_soil_ht_f(self, horizon_dict_with_value):
#         new_value_to_write = []
#         soil_dict_nodes = self.return_soil_nodes()
#         for horizon in horizon_dict_with_value:
#             for node in soil_dict_nodes[horizon]:
#                 new_value_to_write.append(horizon_dict_with_value[horizon])
#         with open(self.soil_ht_path, 'w') as file:
#             for item in new_value_to_write:
#                 file.write(f"{item}\n")
#
#     # parse the ana file
#     def rzwqm_res_parse(self, var_name):
#         # this function is to parse the rzwqm result, and return only the required column as list
#         # should have a list for corresponding var's column number
#         # for snow, it should be 91
#         if var_name == 'snow':
#             column_num = 91
#         elif var_name == 'tile_drainage':
#             column_num = 10
#         julien_day_col = 0
#         lines = self.read_text_file(self.simulate_path)
#         del lines[0]
#         # result starts at index #23
#         lines = lines[23:]
#         desired_data = {}
#
#         for line in lines:
#             try:
#                 if var_name == 'tile_drainage':
#                     # output drainage volume in mm
#                     desired_data[datetime.strptime(line[julien_day_col], '%Y.%j')] = float((line[column_num])) * 10
#                 else:
#                     desired_data[datetime.strptime(line[julien_day_col], '%Y.%j')] = float((line[column_num]))
#             except Exception as e:
#                 print(e)
#                 year = line[julien_day_col].split('.')[0]
#                 if var_name == 'tile_drainage':
#                     # output drainage volume in mm:
#                     desired_data[datetime.strptime(year + '.' + '001', '%j%Y')] = float(
#                         (line[column_num])) * 10
#                 else:
#                     desired_data[datetime.strptime(year + '.' + '001', '%j%Y')] = float(
#                         (line[column_num]))
#
#         return desired_data
#
#     # parse the met file
#     def rzwqm_met_parse(self):
#         # this function parses the met file
#         head = self.met_data[0:36]
#         content = self.met_data[36:]
#         parsed_content = []
#         for line in content:
#             split_line = line.split()
#             parsed_content.append(split_line)
#         return {'head': head, 'parsed_content': parsed_content}
#
#     def rzwqm_return_precipitation(self):
#         precipitation_dict = {}
#         lines = self.rzwqm_met_parse()['parsed_content']
#
#         for line in lines:
#             try:
#                 precipitation_dict[datetime.strptime(line[0] + line[1], '%j%Y')] = float(line[9])
#             except Exception as e:
#                 continue
#
#         return precipitation_dict
#
#     def rzwqm_met_quality_check(self):
#         parsed_met = self.rzwqm_met_parse()
#         # for each line, [0] is day, [1] is year, [2] is Tmin, [3] is Tmax,
#         # [4] is U, [5] is Rad, [6] is E-pan, [7] is RH, [8] is Par, [9] is Rain
#         for line in parsed_met['parsed_content']:
#             # check if tmin is less than tmax:
#             if float(line[2]) > float(line[3]):
#                 # switch the tmin and tmax
#                 tmin = line[3]
#                 tmax = line[2]
#                 line[3] = str(tmax)
#                 line[2] = str(tmin)
#             # check RH:
#             if float(line[7]) > 100:
#                 line[7] = '100'
#         write_to_rzwqm_met(self.met_path, parsed_met['parsed_content'],
#                            parsed_met['head'])
#
#     # write to the met file
#     @staticmethod
#     def rzwqm_met_modify(new_var_list, parsed_content):
#         new_met_now = parsed_content['parsed_content']
#         for data in new_var_list:
#             for count, og_data in enumerate(new_met_now):
#                 fmt = '%Y%j'
#                 jdate = og_data[1] + og_data[0]
#                 og_date = datetime.strptime(jdate, fmt)
#                 if data['date'].date() == og_date.date():
#                     if float(new_met_now[count][9]) == 0:
#                         # print(f"new rain is {data['new_value']}, and old rain is {new_met_now[count][9]}")
#                         new_met_now[count][9] = data['new_value']
#                         break
#         parsed_content['parsed_content'] = new_met_now
#         return parsed_content
#
#     @staticmethod
#     def rzwqm_met_tweak(data_list, parsed_content, index, condition, fmt, snow_i=None):
#         del data_list[0]
#         new_met_now = parsed_content['parsed_content']
#         c_dates = []
#         for data in data_list:
#             c_date = datetime.strptime(data['date'], fmt)
#             c_dates.append({c_date: data['observed'], 'dif': data['dif']})
#
#         for c_date in c_dates:
#             for count, og_data in enumerate(new_met_now):
#                 fmt_og = '%Y%j'
#                 jdate = og_data[1] + og_data[0]
#                 og_date = datetime.strptime(jdate, fmt_og)
#                 if list(c_date.keys())[0].date() == og_date.date():
#                     val = float(new_met_now[count][9])
#                     prev_val = float(new_met_now[count - 1][9])
#                     if snow_i:
#                         if c_date['dif'] == 100:
#                             new_met_now[count][9] = list(c_date.values())[0] * snow_i
#                             if not og_date - timedelta(days=1) in c_dates:
#                                 new_met_now[count - 1][9] = list(c_date.values())[0] * snow_i
#                     elif condition == 'less' and c_date['dif'] != 100:
#                         new_met_now[count][9] = val * index
#                         if not og_date - timedelta(days=1) in c_dates:
#                             new_met_now[count - 1][9] = prev_val / index
#                     elif condition == 'over':
#                         new_met_now[count][9] = val * index
#                         if not og_date - timedelta(days=1) in c_dates:
#                             new_met_now[count - 1][9] = prev_val * index
#                     break
#
#         parsed_content['parsed_content'] = new_met_now
#         return parsed_content
#
#     def rzwqm_general_text_parse(self, out_file_name, head_end):
#         path = os.path.join(self.rzwqm_project_path, out_file_name)
#         with open(path) as f:
#             lines = [line.rstrip('\n') for line in f]
#         head = lines[0:head_end]
#         content = lines[head_end:]
#         parsed_content = []
#         for line in content:
#             split_line = line.split()
#             parsed_content.append(split_line)
#         return {'head': head, 'parsed_content': parsed_content}
#
#     @staticmethod
#     def change_param_val_in_one_line(columns_with_val, line):
#         changed = line.split()
#         for val in columns_with_val.keys():
#             changed[val] = columns_with_val[val]
#         return changed
#
#     # this is to parse the layer.plt file, mainly for soil temperature for now. 09/30/22
#     @staticmethod
#     def rzwqm_parse_layer(desired_depth, file, head_end, column_num):
#         # desired_dates = return_layer_date_count('2000-01-01', '2005-12-31', 11, 4, '%Y-%m-%d')
#         content = file[head_end:]
#         parsed_content = []
#         for line in content:
#             split_line = line.split()
#             parsed_content.append(split_line)
#         return_obj = {}
#         for data in parsed_content:
#             # the_depth is the depth from the layer.plt file
#             the_depth = int(float(data[1]))
#             # organize the soil temperature based on nodes
#             if the_depth in desired_depth:
#                 try:
#                     if return_obj[the_depth]:
#                         return_obj[the_depth].append(float(data[column_num]))
#                 except Exception as e:
#                     return_obj[the_depth] = []
#                     return_obj[the_depth].append(float(data[column_num]))
#         return return_obj
#
#     # the function returns the nodes descritized by RZWQM in a list
#     def parse_soil_discretization_nodes(self):
#         soil_nodes_head_identifier = '=       record (depth increasing with node no.)'
#         soil_nodes_end_identifier = '=         SOIL HORIZON PHYSICAL PROPERTIES'
#         lines = find_desired_line_numbers(soil_nodes_head_identifier, soil_nodes_end_identifier,
#                                           self.dat_data, 3, 2)
#         nodes = []
#         for num in range(lines[0], lines[1] + 1):
#             line = self.dat_data[num].split()
#             depth = int(float(line[1]))
#             nodes.append(depth)
#         return nodes
#
#     def return_soil_nodes(self):
#         head, end = self.line_of_soil_node()
#         soil_horizons = self.return_soil_layer_depth_dict()
#         node_lines = {}
#         for node in range(head, end + 1):
#             split_node = self.dat_data[node].split()
#             node_lines[int(split_node[0])] = float(split_node[1])
#         soil_nodes = {}
#         last_horizon_depth = 0
#         for horizon in soil_horizons:
#             temp_list = []
#             for node in node_lines:
#                 if last_horizon_depth < node_lines[node] < soil_horizons[horizon]:
#                     temp_list.append(node)
#                 elif node_lines[node] == soil_horizons[horizon]:
#                     temp_list.append(node)
#                     last_horizon_depth = soil_horizons[horizon]
#                     break
#
#             soil_nodes[horizon] = temp_list
#         return soil_nodes
#
#     def return_soil_temperature(self, column_num):
#         head_line = find_desired_line_numbers(
#             '****************** DATA STARTS HERE *****************',
#             '', self.layer_data, 1, 1)[0]
#         soil_temp = self.rzwqm_parse_layer(self.parse_soil_discretization_nodes(),
#                                            self.layer_data, head_line, column_num)
#         return soil_temp
#
#
#
#     def dates_value_dict_gen(self, value_list):
#         returing_dict = {}
#         starting_date, ending_date = self.scenario_start_end_date
#         dates_list = loop_between_dates(starting_date, ending_date)
#
#         for count, date_each_day in enumerate(dates_list):
#             try:
#                 returing_dict[date_each_day] = value_list[count]
#             except IndexError as e:
#                 break
#         return returing_dict
#
#     def line_number_of_soil_hydraulic(self):
#         head, end = find_desired_line_numbers(soil_hydraulic_properties_identifier['head'],
#                                               soil_hydraulic_properties_identifier['end'], self.dat_data, 2, 2)
#         return head, end
#
#     def line_number_of_snow_param(self):
#         head, end = find_desired_line_numbers(albedo_identifier['head'],
#                                               albedo_identifier['end'], self.dat_data, 2, 2)
#         return head, end
#
#     def line_number_of_env_prop(self):
#         head, end = find_desired_line_numbers(snow_identifier['head'],
#                                               snow_identifier['end'], self.sno_data, 3, 3)
#         return head, end
#
#     def line_number_of_soil_temperature(self):
#         headline_number = find_desired_line_numbers('****************** DATA STARTS HERE *****************', '',
#                                                     self.layer_data, 1, 1)[0]
#         return headline_number, len(self.layer_data)
#
#     def line_of_soil_physical_depth(self):
#         head, end = find_desired_line_numbers(soil_physical_identifer['head'], soil_physical_identifer['end'],
#                                               self.dat_data, 2, 3)
#         return head, end
#
#     def line_of_soil_physical_properties(self):
#         head, end = find_desired_line_numbers(soil_physical_properties_identifer['head'],
#                                               soil_physical_properties_identifer['end'],
#                                               self.dat_data, 2, 2)
#         return head, end
#
#     def line_of_soil_node(self):
#         head, end = find_desired_line_numbers(soil_node_identifier['head'],
#                                               soil_node_identifier['end'],
#                                               self.dat_data, 3, 2)
#         return head, end
#
#     @sno_path.setter
#     def sno_path(self, value):
#         self._sno_path = value
#
#     @staticmethod
#     def read_text_file(path):
#         with open(path) as f:
#             lines = [line.rstrip('\n') for line in f]
#         parsed_data_all = []
#         for line in lines:
#             # print(line)
#             split_line = line.split()
#             parsed_data_all.append(split_line)
#         # print(parsed_data_all)
#         return parsed_data_all
#
# if __name__ == '__main__':
#     rz = RZWQM('C://RZWQM2/manitoba_waterloo//', '50208701')
#     soil = rz.return_soil_temperature(4)
#     write_list_to_csv(soil[100], 'soil_temp_sim.csv')

import math
import platform
import shutil
from math import log, exp
from shutil import copytree
from datetime import datetime, timedelta
import os

# Optional imports — only needed for Manitoba-specific mass generation
# and database-backed workflows. Core functions (pedotransfer, RZWQM class,
# soil_texture_setter, nlayer_gen, etc.) work without these.
try:
    from data_calibration.data_calibration import Manitoba_data_retrieve
except ImportError:
    Manitoba_data_retrieve = None
try:
    from manitoba_env_data_handle.manitoba_db import select_all_from_multi_col, \
        return_start_and_end_each_station, add_station_meta_value
except ImportError:
    select_all_from_multi_col = None
    return_start_and_end_each_station = None
    add_station_meta_value = None
try:
    from rzwqm.soil_char_retri import canada_soil_db_retrieve
except ImportError:
    try:
        from soil_char_retri import canada_soil_db_retrieve
    except ImportError:
        canada_soil_db_retrieve = None
try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    relativedelta = None
try:
    from db.db_commands import select_one_value_from_a_col_with_condition
except ImportError:
    select_one_value_from_a_col_with_condition = None

soil_hydraulic_properties_identifier = {
    'head': '= . . . Repeat for each horizon',
    'end': '=        SOIL HORIZON HEAT MODEL PARAMETERS'
}

albedo_identifier = {
    'head': '=    21      Maxiumum Crop Coefficient                         [0.0-1.3]',
    'end': '==                 S U R F A C E   R E S I D U E                      =='
}

snow_identifier = {
    'head': '=   1.5    PRECIP ALL SNOW IF MAX TEMPERATURE BELOW THIS VALUE [F]',
    'end': '=     ALBEDO ADJUSTMENTS'
}

soil_physical_identifer = {
    'head': '=      ...repeated for each horizon',
    'end': '==        NUMERICAL SYSTEM CONFIGURATION                              =='
}

soil_physical_properties_identifer = {
    'head': '= . . . Repeat for each horizon, soil surface to profile bottom',
    'end': '=        SOIL HORIZON HYDRAULIC PROPERTIES'
}

soil_node_identifier = {
    'head': '=       record (depth increasing with node no.)',
    'end': '=         SOIL HORIZON PHYSICAL PROPERTIES'
}

soil_heat_model_parameter_identifier = {
    'head': '=            . . . Repeat for each horizon',
    'end': '==            M A C R O P O R E  and  I N F I L T R A T I O N         =='}

soil_infiltration_parameter_identifier = {
    'head': '=    19      Wilting Point water suction head           [ < -10000 cm] ',
    'end': '=     micropore information'
}

soil_micropore_parameter_identifier = {
    'head': '=     ...  repeat record number 2 for each horizon',
    'end': '=     macropore information'
}

soil_macropore_parameter_identifier = {
    'head': '=     ...  repeat this record for each horizon',
    'end': '==            P O T E N T I A L   E V A P O R A T I O N               =='
}

grid_general_property_identifier = {
    'head': '=     8      ambient co2 [ppm]',
    'end': '==         SOIL PROPERTIES AND PARAMETERS                             =='
}

rz_init_water_identifer = {
    'head': '=            ... repeat record 2 for all horizons',
    'end': '==                   S O I L   C H E M I S T R Y                      =='
}

rz_init_soil_chemistry_identifer = {
    'head': '=    (Repeat records 1-3 for each soil horizon)',
    'end': '==                      N U T R I E N T                               =='
}

rz_init_soil_nutrient_identifer = {
    'head': '=       ...repeat For each horizon',
    'end': '==                      P E S T I C I D E S                           =='
}

# --- Management section identifiers ---
plant_management_identifier = {
    'head': '=    5       planting window in days after plant date (# of days) [0-45]',
    'end': '==               M A N U R E   M A N A G E M E N T                    =='
}

manure_management_identifier = {
    'head': '=     3...   repeat record 2 for each application.',
    'end': '==            F E R T I L I Z E R   M A N A G E M E N T               =='
}

fertilizer_management_identifier = {
    'head': '=     ...   repeat record 2 for each application.',
    'end': '==                   B M P   M A N A G E M E N T                      =='
}

bmp_management_identifier = {
    'head': '=     11     Depth of anhydrous injector used for fertlizer app      [cm]',
    'end': '==            P E S T I C I D E   M A N A G E M E N T                 =='
}

pesticide_management_identifier = {
    'head': '=   ...   repeat records 2-4 for each application',
    'end': '==            T I L L A G E   M A N A G E M E N T                     =='
}

tillage_management_identifier = {
    'head': '=     ...  repeat record 2 for each operation',
    'end': '==            T I L E H E A D G A T E      M A N A G E M E N T        =='
}

irrigation_management_identifier = {
    'head': '=   . . .  repeat Rec 2-4 for each operation',
    'end': 'DONE'  # last section in file; use special sentinel
}

input_date_format = '%Y-%m-%d'


# this is the class the python file describing the different properties for the rz setup

def is_datetime_in_months(datetime_obj, months):
    """
    Determine whether a given datetime object is in any of the specified months.

    Parameters:
    - datetime_obj: A datetime object
    - months: A list of strings representing the months (e.g., ["January", "February", ...])

    Returns:
    - True if the datetime object is in any of the specified months, False otherwise.
    """
    # Convert the month names to their corresponding numerical representations
    month_to_number = {
        'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
        'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
    }
    month_numbers = [month_to_number.get(month, None) for month in months]

    # Remove None values (invalid month names)
    month_numbers = [x for x in month_numbers if x is not None]

    if not month_numbers:
        return False  # All month names are invalid

    # Check if the datetime object is in any of the specified months
    return datetime_obj.month in month_numbers


def filter_by_ldepth(df):
    """Filter rows where 'LDEPTH' is less than or equal to 0."""
    return df[df['LDEPTH'] > 0].copy()


def filter_by_clay(df):
    return df[df['TCLAY'] > 0].copy()


def find_desired_line_numbers(head_identifier, end_identifier, the_file, lines_from_identifer_head_to_increase,
                              lines_from_identifier_end_to_decrease):
    first_line_num = 0
    end_line_num = 0
    for count, line in enumerate(the_file):
        if line == head_identifier:
            first_line_num = count + lines_from_identifer_head_to_increase
        elif line == end_identifier:
            end_line_num = count - lines_from_identifier_end_to_decrease
    return first_line_num, end_line_num


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


def custom_date_format(dt):
    month = str(dt.month)
    day = str(dt.day)
    year = str(dt.year)
    return f"{day} {month} {year}"


def initialize_scneario_based_on_existing(original_instance_project_path, original_instance_name, name_of_new_instance,
                                          if_snow, operation_date, if_met=False):
    # create instance
    src = original_instance_project_path + original_instance_name
    dst = original_instance_project_path + name_of_new_instance
    # overwrite existing directory
    if os.path.exists(dst):
        shutil.rmtree(dst)

    copytree(src, dst)
    # change ipnames for the instance
    rz = RZWQM(original_instance_project_path, name_of_new_instance)
    ip = rz.ipnames
    ip[0] = original_instance_project_path + name_of_new_instance + "//cntrl.dat"
    ip[1] = original_instance_project_path + name_of_new_instance + "//rzwqm.dat"
    ip[4] = original_instance_project_path + name_of_new_instance + "//rzinit.dat"
    ip[5] = original_instance_project_path + name_of_new_instance + "//plgen.dat"
    if if_snow:
        src_sno_file = original_instance_project_path + 'Meteorology//' + original_instance_name + '.sno'
        dst_snow_file = original_instance_project_path + 'Meteorology//' + name_of_new_instance + '.sno'
        shutil.copyfile(src_sno_file, dst_snow_file)
        ip[6] = original_instance_project_path + 'Meteorology//' + name_of_new_instance + '.sno'
    if if_met:
        ip[2] = original_instance_project_path + 'Meteorology//' + name_of_new_instance + '.met'
        ip[3] = original_instance_project_path + 'Meteorology//' + name_of_new_instance + '.brk'

    ip[7] = original_instance_project_path + "Analysis" + "//" + name_of_new_instance + ".ana"
    ip[8] = custom_date_format(operation_date[0]) + '  ' + custom_date_format(operation_date[1])
    with open(rz.ipnames_path, 'w') as file:
        for line in ip:
            file.write(line + '\n')
    print(name_of_new_instance + ' ' + 'created')


MAXNOD = 300  # Maximum number of nodes
MAXHOR = 20  # Maximum number of horizons


# Function Definitions for node generation
def makedelz(lasthorizon):
    i = 0
    jump = 1.0
    maxval = 5.0
    delz = [0] * MAXNOD

    # Determine maxval based on the last horizon
    if lasthorizon <= 1400:
        maxval = 5.0
    elif 1400 < lasthorizon <= 2000:
        maxval = 7.0
    elif 2000 < lasthorizon <= 2500:
        maxval = 9.0
    elif 2500 < lasthorizon <= 3000:
        maxval = 11.0

    while jump < maxval:
        delz[i] = delz[i + 1] = jump
        i += 2
        jump += 2.0

    if i < MAXNOD:
        for idx in range(i, MAXNOD):
            delz[idx] = jump

    return delz


def maketl(delz):
    tl = [1.0] + [(delz[i] + delz[i - 1]) * 0.5 for i in range(1, MAXNOD)]
    return tl


def maketlt(tl):
    tlt = [tl[0]]
    for i in range(1, MAXNOD):
        tlt.append(tlt[i - 1] + tl[i])
    return tlt


def reset_tl(delz, tl, pos):
    tl[pos] = (delz[pos] + delz[pos - 1]) * 0.5
    tl[pos + 1] = (delz[pos + 1] + delz[pos]) * 0.5


def mirror(delz, pos):
    if delz[pos - 1] != 1.0:
        delz[pos + 1] = delz[pos - 1]


def halfwayrule(delz, pos, horizonnum):
    testval = delz[pos] * 2.0
    if testval > delz[pos - 1] or (delz[pos] == 1.0 and horizonnum == 0):
        return True
    else:
        return False


def decrement_delz(delz, tl, tlt, horizonnum, horizonbound, pos, setnode):
    dec_val = 2.0
    setnode_error = False

    delz[pos] -= dec_val
    success = halfwayrule(delz, pos, horizonnum)
    if not success:
        delz[pos] += dec_val
        if pos - 1 == setnode:
            setnode_error = True
            return setnode_error
        setnode_error = decrement_delz(delz, tl, tlt, horizonnum, horizonbound, pos - 1, setnode)

    return setnode_error


def forwardhalf(delz, pos, tl):
    testvalue = delz[pos - 1] * 2.0
    while delz[pos] > testvalue:
        decval = 2.0
        delz[pos] -= decval
        reset_tl(delz, tl, pos)
        forwardhalf(delz, pos + 1, tl)


def trygoingup(delz, pos):
    decval = 2.0
    delz[pos] += decval


# Integrate everything into ncoslyr
def ncoslyr(m_horthk, m_nhor):
    # Initialize variables
    done = 0
    pos = 0
    start = 0
    setnode = -1
    setnode_error = False
    mr_sulu = True
    horizons = [0] * MAXHOR
    tlt = [0] * MAXNOD
    delz = [0] * MAXNOD
    tl = [0] * MAXNOD

    k = m_nhor - 1
    horizons[:m_nhor] = m_horthk[:m_nhor]

    if horizons[k] > 3000:
        horizons[k] = 3000.0

    # Initialize the computational layers
    delz = makedelz(horizons[k])
    tl = maketl(delz)
    tlt = maketlt(tl)

    i = 0
    start = 1 if horizons[0] <= 1.0 else 0

    for j in range(start, m_nhor - 1):
        while not done:
            if tlt[i] >= horizons[j]:
                done = 1
            i += 1
        pos = i - 1
        done = 0

        while True:
            if tlt[pos] == horizons[j] or pos == setnode:
                break

            setnode_error = decrement_delz(delz, tl, tlt, j, horizons[j], pos, setnode)
            if setnode_error:
                return False  # Exit the function, error occurred

            tl = maketl(delz)
            tlt = maketlt(tl)

            if tlt[pos] < horizons[j]:
                trygoingup(delz, pos)
                reset_tl(delz, tl, pos)
                tlt = maketlt(tl)

        setnode = pos
        setnode_error = False
        mirror(delz, pos)
        forwardhalf(delz, pos + 2, tl)
        reset_tl(delz, tl, pos + 1)
        tlt = maketlt(tl)

    # Update the final horizon depths
    i = 0
    for j in range(m_nhor):
        while tlt[i] < m_horthk[j] and i < MAXNOD - 1:
            i += 1
        horizons[j] = tlt[i]
        # If the horizon depths changed, notify the user
        if m_horthk[j] != horizons[j]:
            print(
                f"To accommodate our numerical layering scheme, one of your horizon depths had to be changed. Original depth: {m_horthk[j]}, New depth: {horizons[j]}")
        m_horthk[j] = horizons[j]

    return [True, delz, tl, tlt]


def nlayer_gen(m_nhor, m_horthk):
    # Initialize the variables
    m_nn = 0  # This will be updated in ncoslyr
    reset_depths = 0
    reset_ok = 0
    zn = [0.0] * MAXNOD

    # Call ncoslyr to get computational layers and modified horizon depths

    bGridStatus = ncoslyr(m_horthk, m_nhor)
    original_hor = m_horthk.copy()
    if bGridStatus == False:
        for i in range(0, m_nhor):
            for count, n in enumerate(range(1, 21)):
                if count < 10:
                    m_horthk[i] = m_horthk[i] - 1
                    if i != 0:
                        if m_horthk[i] <= m_horthk[i - 1]:
                            m_horthk[i] = original_hor[i]
                            continue
                    bGridStatus = ncoslyr(m_horthk, m_nhor)
                    if bGridStatus != False:
                        break
                    else:
                        continue
                else:
                    m_horthk[i] = original_hor[i]
                    if i != m_nhor - 1:
                        if m_horthk[i] >= m_horthk[i + 1]:
                            m_horthk[i] = original_hor[i]
                            continue
                    bGridStatus = ncoslyr(m_horthk, m_nhor)
                    if bGridStatus != False:
                        break
                    else:
                        continue
            if bGridStatus != False:
                break

    m_delz = bGridStatus[1]
    tl = bGridStatus[2]
    tlt = bGridStatus[3]
    if bGridStatus:
        # Update tl, tlt, and zn based on the modified m_delz and m_horthk
        tl[0] = 1.0
        zn[0] = 0.5
        tlt[0] = tl[0]

        for i in range(1, MAXNOD):
            tl[i] = (m_delz[i - 1] + m_delz[i]) * 0.5
            zn[i] = zn[i - 1] + m_delz[i - 1]
            tlt[i] = tlt[i - 1] + tl[i]

        tl[-1] = m_delz[-2]
        tlt[-1] = tlt[-2] + tl[-1]
        zn[-1] = zn[-2] + m_delz[-2]

        return (tlt, m_delz)

    elif m_nn > MAXNOD:
        # Print an error message if too many layers are generated
        print(f"The numerical layering scheme generated TOO MANY layers with the horizons supplied. \
                Please switch horizon depths around a little. Number of layers generated ==> {m_nn}")

        return False, None, None, None


def soil_texture_setter(sand, clay):
    silt = 100 - sand - clay

    if sand + clay > 100 or sand < 0 or clay < 0:
        raise Exception('Inputs adds over 100% or are negative')

    elif silt + 1.5 * clay < 15:
        textural_class = 'sand'

    elif silt + 1.5 * clay >= 15 and silt + 2 * clay < 30:
        textural_class = 'loamy sand'

    elif (clay >= 7 and clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (
            clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        textural_class = 'sandy loam'

    elif clay >= 7 and clay < 27 and silt >= 28 and silt < 50 and sand <= 52:
        textural_class = 'loam'

    elif (silt >= 50 and clay >= 12 and clay < 27) or (silt >= 50 and silt < 80 and clay < 12):
        textural_class = 'silt loam'

    elif silt >= 80 and clay < 12:
        textural_class = 'silt'

    elif clay >= 20 and clay < 35 and silt < 28 and sand > 45:
        textural_class = 'sandy clay loam'

    elif clay >= 27 and clay < 40 and sand > 20 and sand <= 45:
        textural_class = 'clay loam'

    elif clay >= 27 and clay < 40 and sand <= 20:
        textural_class = 'silty clay loam'

    elif clay >= 35 and sand > 45:
        textural_class = 'sandy clay'

    elif clay >= 40 and silt >= 40:
        textural_class = 'silty clay'

    elif clay >= 40 and sand <= 45 and silt < 40:
        textural_class = 'clay'

    else:
        textural_class = 'na'

    return textural_class


def soil_default_setter(textural_class):
    texture_dict = {
        "sand": {
            "ws": 0.437,
            "wr": 0.02,
            "bubbling_pressure": 7.26,
            "pore_size_dist": 0.592,
            "fc33": 0.0632,
            "fc15": 0.0245,
            "ksat": 21.0
        },
        "loamy sand": {
            "ws": 0.437,
            "wr": 0.035,
            "bubbling_pressure": 8.69,
            "pore_size_dist": 0.474,
            "fc33": 0.1063,
            "fc15": 0.0467,
            "ksat": 6.11
        },
        "sandy loam": {
            "ws": 0.453,
            "wr": 0.041,
            "bubbling_pressure": 14.66,
            "pore_size_dist": 0.322,
            "fc33": 0.1916,
            "fc15": 0.0852,
            "ksat": 2.59
        },
        "loam": {
            "ws": 0.463,
            "wr": 0.027,
            "bubbling_pressure": 11.15,
            "pore_size_dist": 0.22,
            "fc33": 0.2334,
            "fc15": 0.1163,
            "ksat": 1.32
        },
        "siltyloam": {
            "ws": 0.501,
            "wr": 0.015,
            "bubbling_pressure": 20.76,
            "pore_size_dist": 0.211,
            "fc33": 0.2855,
            "fc15": 0.1361,
            "ksat": 0.68
        },
        "silt": {
            "ws": 0.501,
            "wr": 0.015,
            "bubbling_pressure": 20.76,
            "pore_size_dist": 0.211,
            "fc33": 0.2855,
            "fc15": 0.1361,
            "ksat": 0.68
        },
        "sandy clay loam": {
            "ws": 0.398,
            "wr": 0.068,
            "bubbling_pressure": 28.08,
            "pore_size_dist": 0.25,
            "fc33": 0.2457,
            "fc15": 0.1366,
            "ksat": 0.43
        },
        "clay loam": {
            "ws": 0.464,
            "wr": 0.075,
            "bubbling_pressure": 25.89,
            "pore_size_dist": 0.194,
            "fc33": 0.3119,
            "fc15": 0.1882,
            "ksat": 0.23
        },
        "silty clay loam ": {
            "ws": 0.471,
            "wr": 0.04,
            "bubbling_pressure": 32.56,
            "pore_size_dist": 0.151,
            "fc33": 0.3433,
            "fc15": 0.2107,
            "ksat": 0.15
        },
        "sandy clay": {
            "ws": 0.43,
            "wr": 0.109,
            "bubbling_pressure": 29.17,
            "pore_size_dist": 0.168,
            "fc33": 0.3221,
            "fc15": 0.2214,
            "ksat": 0.12
        },
        "silty clay": {
            "ws": 0.479,
            "wr": 0.056,
            "bubbling_pressure": 34.19,
            "pore_size_dist": 0.127,
            "fc33": 0.3727,
            "fc15": 0.2513,
            "ksat": 0.09
        },
        "clay": {
            "ws": 0.475,
            "wr": 0.09,
            "bubbling_pressure": 37.3,
            "pore_size_dist": 0.131,
            "fc33": 0.3789,
            "fc15": 0.2655,
            "ksat": 0.06
        }
    }
    return texture_dict[textural_class]


def pore_size_distribution_estimate(fc33, fc15, wr):
    # estimate pore size distribution based on the fc33 fc15 wr
    pore_size_dist = log((fc33 - wr) / (fc15 - wr)) / log(15000 / 333)
    return pore_size_dist


def N2_estimate(pore_size_dist):
    N2 = 2 + 3 * pore_size_dist
    return N2


def B_estimate(fc33, wr, pore_size_dist):
    B = (fc33 - wr) * 333 ** pore_size_dist
    return B


def bubbling_pressure_estimate(ws, pore_size_dist, wr, B, ):
    bubbling_pressure = exp((log(B) - log(ws - wr)) / pore_size_dist)
    return bubbling_pressure


def C2_estimate(bubbling_pressure, pore_size_dist, ksat, N1):
    C2 = (ksat * bubbling_pressure) ** (pore_size_dist - N1)
    return C2


def fc10_estimate(ws, wr, bubbling_pressure, pore_size_dist):
    # Brooks-Corey water retention at 1/10 bar (100 cm suction)
    # θ(h) = θr + (θs - θr) * (hb/h)^λ
    fc10 = (ws - wr) * (bubbling_pressure / 100.0) ** pore_size_dist + wr
    return fc10


def default_microporosity_for_each_soil_type(soil_type):
    if soil_type == "sandy loam":
        return 0.19
    elif soil_type == "sandy clay loam":
        return 0.347
    elif soil_type == "clay loam":
        return 0.41
    elif soil_type == "silty clay loam ":
        return 0.452
    elif soil_type == "sandy clay":
        return 0.52
    elif soil_type == "silty clay":
        return 0.53
    elif soil_type == "clay":
        return 0.564
    elif soil_type == "sand":
        return 0.057
    elif soil_type == "loamy sand":
        return 0.108
    elif soil_type == 'loam':
        return 0.254
    elif soil_type == 'silty loam':
        return 0.274
    elif soil_type == 'silt':
        return 0.274


class soil_hydraulic_properties_each_horizon:
    def __init__(self, pore_size_dist, saturated_water_content,
                 residual_water_content, bubbling_pressure, constant_for_oh, lateral_ksat, ksat, eps,
                 second_intercept_c2, horizon_num, fc33, fc10, fc15):
        self.bubbling_pressure = bubbling_pressure
        self.pore_size_dist = pore_size_dist
        self.saturated_water_content = saturated_water_content
        self.residual_water_content = residual_water_content
        self.constant_for_oh = constant_for_oh
        self.lateral_ksat = lateral_ksat
        self.ksat = ksat
        self.eps = eps
        self.second_intercept_c2 = second_intercept_c2
        self.horizon_num = horizon_num
        self.fc33 = fc33
        self.fc10 = fc10
        self.fc15 = fc15

    def fc33_estimate(self):
        B1 = (self.saturated_water_content - self.residual_water_content - self.constant_for_oh * abs(self.bubbling_pressure))  * abs(self.bubbling_pressure) ** self.pore_size_dist
        fc33 = B1 / (333 ** self.pore_size_dist) + self.residual_water_content
        return round(fc33, 2)

    def fc10_estimate(self):
        B1 = (
                     self.saturated_water_content - self.residual_water_content - self.constant_for_oh * abs(
                 self.bubbling_pressure)) \
             * abs(self.bubbling_pressure) ** self.pore_size_dist
        fc10 = B1 / (100 ** self.pore_size_dist) + self.residual_water_content
        return round(fc10, 2)

    def fc15_estimate(self):
        B1 = (
                     self.saturated_water_content - self.residual_water_content - self.constant_for_oh * abs(
                 self.bubbling_pressure)) \
             * abs(self.bubbling_pressure) ** self.pore_size_dist
        # 15000 is head of wilting point, assuing that 15 bar is the wilting point
        fc15 = B1 / (15000 ** self.pore_size_dist) + self.residual_water_content
        return round(fc15, 2)


class soil_physical_properties_each_horizon:
    def __init__(self, bulk_density, particle_density, sand, silt, clay):
        self.bulk_density = bulk_density
        self.particle_density = particle_density
        self.porosity = round(1 - (bulk_density / particle_density), 2)
        self.sand = sand
        self.silt = silt
        self.clay = clay


class soil_infiltration_properties:
    def __init__(self, surface_crust_present, crust_hydraulic_conductivity, bottom_boundry_condition,
                 Field_saturation_fraction, Convergence_Criteria, Maximum_number_of_iterations,
                 Maximum_number_of_cycles, Management_cutoff_threshold_for_soil_moisture_content,
                 Perched_water_table, water_table_leakage_rate, Drains_are_present, depth_from_surface_to_drains,
                 drain_spacing, radius_of_drain, Init_gradient_flow, Lateral_hydraulic_gradient,
                 Minimum_water_suction_head, Field_Capacity_water_suction_head, Wilting_Point_water_suction_head):
        self.surface_crust_present = surface_crust_present
        self.crust_hydraulic_conductivity = crust_hydraulic_conductivity
        self.bottom_boundry_condition = bottom_boundry_condition
        self.Field_saturation_fraction = Field_saturation_fraction
        self.Convergence_Criteria = Convergence_Criteria
        self.Maximum_number_of_iterations = Maximum_number_of_iterations
        self.Maximum_number_of_cycles = Maximum_number_of_cycles
        self.Management_cutoff_threshold_for_soil_moisture_content = Management_cutoff_threshold_for_soil_moisture_content
        self.Perched_water_table = Perched_water_table
        self.water_table_leakage_rate = water_table_leakage_rate
        self.Drains_are_present = Drains_are_present
        self.depth_from_surface_to_drains = depth_from_surface_to_drains
        self.drain_spacing = drain_spacing
        self.radius_of_drain = radius_of_drain
        self.Init_gradient_flow = Init_gradient_flow
        self.Lateral_hydraulic_gradient = Lateral_hydraulic_gradient
        self.Minimum_water_suction_head = Minimum_water_suction_head
        self.Field_Capacity_water_suction_head = Field_Capacity_water_suction_head
        self.Wilting_Point_water_suction_head = Wilting_Point_water_suction_head


class soil_macropore_properties_each_horizon:
    def __init__(self, total_macroporosity, average_radius, width, crack_length, length_of_aggregate,
                 fraction_of_dead_end):
        self.total_macroporosity = total_macroporosity
        self.average_radius = average_radius
        self.width = width
        self.crack_length = crack_length
        self.length_of_aggregate = length_of_aggregate
        self.fraction_of_dead_end = fraction_of_dead_end


class soil_macropore_general_properties:
    def __init__(self, macropores_present, sorptivity_factor, tile_drain_express, radial_holes, cracks_columns):
        self.macropores_present = macropores_present
        self.sorptivity_factor = sorptivity_factor
        self.tile_drain_express = tile_drain_express
        self.radial_holes = radial_holes
        self.cracks_columns = cracks_columns


class grid_general_property:
    def __init__(self, area, elevation, aspect_measured_clockwise, center_lat, center_lon, slope, rainfall_zone,
                 ambient_co2):
        self.area = area
        self.elevation = elevation
        self.aspect_measured_clockwise = aspect_measured_clockwise
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.slope = slope
        self.rainfall_zone = rainfall_zone
        self.ambient_co2 = ambient_co2


class rz_init_water_cont_each_horizon:
    def __init__(self, water_level, temperature):
        self.water_level = water_level
        self.temperature = temperature


class rz_init_water_content_setting:
    def __init__(self, tensio_or_wr_flag, conti_flag):
        self.tensio_or_wr_flag = tensio_or_wr_flag
        self.conti_flag = conti_flag


def write_to_rzwqm_met(name, parsed_content, head):
    to_write = []
    for line in parsed_content:
        s = f"   {line[0]}   {line[1]}   {line[2]}   {line[3]}   {line[4]}   {line[5]}   {line[6]}   {line[7]}   {line[8]}    {line[9]}"
        to_write.append(s)
    head.extend(to_write)
    with open(name, 'w') as file:
        for line in head:
            file.write(line + '\n')


class RZWQM:
    @property
    def sno_path(self):
        return self._sno_path

    def __init__(self, project_path, station):
        self.station = station
        self.met_path = project_path + "/Meteorology/" + station + '.met'
        self.sno_path = project_path + "/Meteorology/" + station + '.sno'
        self.rzwqm_project_path = project_path
        self.simulate_path = project_path + '/Analysis/' + station + '.ana'
        self.dat_path = self._resolve_case(project_path + station, 'RZWQM.dat', 'rzwqm.dat')
        self.init_path = self._resolve_case(project_path + station, 'RZINIT.dat', 'rzinit.dat')
        self.ipnames_path = self._resolve_case(project_path + station, 'IPNAMES.DAT', 'ipnames.dat')
        self.kf_path = project_path + station + '/KF.txt'
        self.soil_ht_path = project_path + station + '/soil_ht_f.txt'
        self.soil_tk_path = project_path + station + '/soil_tk_f.txt'
        self.brk_path = project_path + "/Meteorology/" + station + '.brk'

    @staticmethod
    def _resolve_case(directory, name_a, name_b):
        """Return whichever filename actually exists on disk; prefer name_a."""
        path_a = os.path.join(directory, name_a)
        if os.path.isfile(path_a):
            return path_a
        path_b = os.path.join(directory, name_b)
        if os.path.isfile(path_b):
            return path_b
        return path_a  # default to name_a if neither exists yet

    def check_if_dat_exist(self):
        if not os.path.isfile(self.dat_path):
            return False
        else:
            return True

    @property
    def dat_data(self):
        with open(self.dat_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]
        return lines

    @property
    def layer_data(self):
        layer_path = self._resolve_case(
            self.rzwqm_project_path + self.station, 'LAYER.PLT', 'Layer.plt')
        with open(layer_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]
        return lines

    @property
    def ipnames(self):
        with open(self.ipnames_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]
        return lines

    @property
    def met_data(self):
        with open(self.met_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]
        return lines

    @property
    def sno_data(self):
        with open(self.sno_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]
        return lines

    @property
    def init_data(self):
        with open(self.init_path, encoding="ISO-8859-1") as f:
            lines = [line.rstrip('\n') for line in f]
        return lines

    @property
    def scenario_start_end_date(self):
        date_line = self.ipnames[8]
        date_line = date_line.split()
        starting_date = datetime.strptime(date_line[0] + date_line[1] + date_line[2], '%d%m%Y')
        ending_date = datetime.strptime(date_line[3] + date_line[4] + date_line[5], '%d%m%Y')
        return starting_date, ending_date

    # returns the hydraulic properties for each horzion based on the rzwqm.dat file inputted
    def return_the_soil_properties_class(self):
        head_num, end_num = self.line_number_of_soil_hydraulic()
        dict_with_properties = {}
        soil_property_for_one_horizon = []
        for count, line in enumerate(self.dat_data[head_num:end_num + 1]):
            try:
                # every three lines is a horizon
                if (count + 1) % 3 == 0:
                    soil_property_for_one_horizon.append(line.split())
                    horizon_num = int(soil_property_for_one_horizon[0][0])
                    bubbling_pressure = round(float(soil_property_for_one_horizon[0][1]), 4)
                    pore_size_dist = round(float(soil_property_for_one_horizon[0][2]), 2)
                    eps = round(float(soil_property_for_one_horizon[0][3]), 2)
                    ksat = round(float(soil_property_for_one_horizon[0][4]), 2)
                    wr = round(float(soil_property_for_one_horizon[0][5]), 2)
                    ws = round(float(soil_property_for_one_horizon[0][6]), 6)
                    fc33 = round(float(soil_property_for_one_horizon[1][0]), 3)
                    fc10 = round(float(soil_property_for_one_horizon[1][1]), 3)
                    fc15 = round(float(soil_property_for_one_horizon[1][2]), 3)
                    second_intercept_c2 = round(float(soil_property_for_one_horizon[1][4]), 2)
                    lateral_ksat = round(float(soil_property_for_one_horizon[2][0]), 2)
                    hydraulic_horizon = soil_hydraulic_properties_each_horizon(
                        pore_size_dist, ws, wr, bubbling_pressure, 0, lateral_ksat, ksat, eps, second_intercept_c2,
                        horizon_num, fc33, fc10, fc15)
                    dict_with_properties[horizon_num] = hydraulic_horizon
                    soil_property_for_one_horizon = []
                else:
                    soil_property_for_one_horizon.append(line.split())
            except TypeError:
                print(count)
        return dict_with_properties

    def return_number_of_soil_horizons(self):
        head_num, end_num = self.line_of_soil_physical_depth()
        number_of_horizons = int(self.dat_data[head_num][0].split()[0])

        return number_of_horizons

    def return_soil_layer_depth_dict(self):
        head_num, end_num = self.line_of_soil_physical_depth()
        number_of_horizons = int(self.dat_data[head_num][0].split()[0])
        soil_layer_dict = {}
        for layer_num in range(1, number_of_horizons + 1):
            line_data = self.dat_data[head_num + layer_num]
            soil_layer_dict[layer_num] = float(line_data.strip())
        return soil_layer_dict

    def return_soil_general_properties(self):
        head_num, end_num = self.line_of_grid_general_properties()
        line = self.dat_data[head_num].split()
        area = line[0]
        elevation = line[1]
        aspect = line[2]
        lat = line[3]
        slope = line[4]
        lon = line[5]
        rainfall_zone = line[6]
        am_co2 = line[7]
        grid_prop = grid_general_property(area, elevation, aspect, lat, lon, slope, rainfall_zone, am_co2)
        return grid_prop

    def write_soil_general_properties_to_dat(self, new_soil_properties):
        modified_dat = self.dat_data
        head_num, end_num = self.line_of_grid_general_properties()
        line = str(new_soil_properties.area) + '  ' + \
               str(new_soil_properties.elevation) + '  ' + \
               str(new_soil_properties.aspect_measured_clockwise) + '  ' + \
               str(new_soil_properties.center_lat) + '  ' + \
               str(new_soil_properties.slope) + '  ' + \
               str(new_soil_properties.center_lon) + '  ' + \
               str(new_soil_properties.rainfall_zone) + '  ' + \
               str(new_soil_properties.ambient_co2)
        modified_dat[head_num] = line
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in modified_dat:
                file.write(line + '\n')

    # change the hydraulic properties and write back to the dat file
    def write_updated_hydraulic_properties_to_dat(self, dict_of_soil_properties):
        head_num, end_num = self.line_number_of_soil_hydraulic()
        modified_dat = self.dat_data
        length_from_dat = end_num - head_num

        if len(dict_of_soil_properties) * 3 - 1 != length_from_dat:
            print('things went wrong when adjusting the calibration input')

        else:
            for key in dict_of_soil_properties:
                property = dict_of_soil_properties[key]
                key = key - 1
                changing_line_first = str(property.horizon_num) + '  ' + str(property.bubbling_pressure) + '  ' + str(
                    property.pore_size_dist) + '  ' + str(property.eps) + '  ' + str(property.ksat) + '  ' + str(
                    property.residual_water_content) + '  ' + str(property.saturated_water_content)

                changing_line_second = str(property.fc33) + '  ' + str(property.fc10) + '  ' + str(
                    property.fc15) + '  ' + str(property.bubbling_pressure) + '  ' + str(
                    property.second_intercept_c2) + '  0  0'

                changing_line_third = str(property.lateral_ksat)

                modified_dat[int(head_num) + key * 3] = changing_line_first
                modified_dat[int(head_num) + key * 3 + 1] = changing_line_second
                modified_dat[int(head_num) + key * 3 + 2] = changing_line_third

        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in modified_dat:
                file.write(line + '\n')

    def write_new_hydraulic_properties_to_dat(self, dict_of_soil_properties):
        head_num, end_num = self.line_number_of_soil_hydraulic()
        modified_dat = self.dat_data
        new_string_list = []

        for key in dict_of_soil_properties:
            property = dict_of_soil_properties[key]
            changing_line_first = str(property.horizon_num) + '  ' + str(property.bubbling_pressure) + '  ' + str(
                property.pore_size_dist) + '  ' + str(property.eps) + '  ' + str(property.ksat) + '  ' + str(
                property.residual_water_content) + '  ' + str(property.saturated_water_content)
            changing_line_second = str(property.fc33) + '  ' + str(property.fc10) + '  ' + str(
                property.fc15) + '  ' + str(property.bubbling_pressure) + '  ' + str(
                property.second_intercept_c2) + '  0  0'
            changing_line_third = str(property.lateral_ksat)
            new_string_list.append(changing_line_first)
            new_string_list.append(changing_line_second)
            new_string_list.append(changing_line_third)

        modified_dat[head_num:end_num + 1] = new_string_list

        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in modified_dat:
                file.write(line + '\n')

    def write_new_soil_physical_properties_to_dat(self, dict_of_soil_physical_properties):
        head_num, end_num = self.line_of_soil_physical_properties()
        modified_dat = self.dat_data
        new_properties_string_list = []
        for layer in dict_of_soil_physical_properties:
            new_properties_string_list.append('Rago Loam')
            each_line = '0  {}  {}  {} {}  {}  {}  '.format(dict_of_soil_physical_properties[layer].particle_density,
                                                            dict_of_soil_physical_properties[layer].bulk_density,
                                                            dict_of_soil_physical_properties[layer].porosity,
                                                            round(dict_of_soil_physical_properties[layer].sand, 2),
                                                            round(dict_of_soil_physical_properties[layer].silt, 2),
                                                            round(dict_of_soil_physical_properties[layer].clay, 2))
            new_properties_string_list.append(each_line)
        modified_dat[head_num:end_num + 1] = new_properties_string_list

        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in modified_dat:
                file.write(line + '\n')

    @staticmethod
    def env_prop(line_num, dat_data):
        # albedo sector only contains one line of data
        # this function parses the environmental properties of the dat file
        dict_with_properties = {}
        traits = dat_data[line_num].split()
        dict_with_properties['dry soil albedo'] = traits[0]
        dict_with_properties['wet soil albedo'] = traits[1]
        dict_with_properties['albedo of the crop at maturity'] = traits[2]
        dict_with_properties['albedo of fresh residue'] = traits[3]
        dict_with_properties['height at which wind measurements are take'] = traits[4]
        dict_with_properties['average sunshine fraction for a day'] = traits[5]
        dict_with_properties['PAN COEFFICIENT'] = traits[6]
        dict_with_properties['Using Hourly weather'] = traits[7]
        dict_with_properties['SHAW'] = traits[8]
        dict_with_properties['Penflux'] = traits[9]
        dict_with_properties['surface soil resistance'] = traits[10]
        dict_with_properties['stress method'] = traits[11]
        dict_with_properties['plastic mulch cover fraction'] = traits[12]
        dict_with_properties['emissivity of canopy'] = traits[13]
        dict_with_properties['emissivity of residue'] = traits[14]
        dict_with_properties['emissivity of snow'] = traits[15]
        dict_with_properties['emissivity of soil'] = traits[16]
        dict_with_properties['emissivity of plastic'] = traits[17]
        dict_with_properties['PET calculation method'] = traits[18]
        dict_with_properties['Initial Crop Coefficient'] = traits[19]
        dict_with_properties['Maxiumum Crop Coefficient'] = traits[20]
        dict_with_properties['Albedo of plastic'] = traits[21]
        dict_with_properties['Transmissivity of plastic'] = traits[22]
        return dict_with_properties

    def write_env_pop_to_dat(self, modified_properties, dat_data, line_num):
        # the function write the edited environmental properties to the dat file there is only one line describing
        # the environmental properties, thus both end line number and start line number can be used
        modified_dat = dat_data
        modified_list = list(modified_properties.values())
        new_str = ''
        for count, val in enumerate(modified_list):
            if count != len(modified_list):
                new_str = new_str + str(val) + '  '
            else:
                new_str = new_str + str(val)
        dat_data[line_num] = new_str
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in modified_dat:
                file.write(line + '\n')

    def write_new_kf(self, new_value):
        with open(self.kf_path, 'w') as file:
            for item in new_value:
                file.write(f"{item}\n")

    def write_new_soil_tk_f(self, horizon_dict_with_value):
        new_value_to_write = []
        soil_dict_nodes = self.return_soil_nodes()
        for horizon in horizon_dict_with_value:
            for node in soil_dict_nodes[horizon]:
                new_value_to_write.append(horizon_dict_with_value[horizon])
        with open(self.soil_tk_path, 'w') as file:
            for item in new_value_to_write:
                file.write(f"{item}\n")

    def write_new_soil_ht_f(self, horizon_dict_with_value):
        new_value_to_write = []
        soil_dict_nodes = self.return_soil_nodes()
        for horizon in horizon_dict_with_value:
            for node in soil_dict_nodes[horizon]:
                new_value_to_write.append(horizon_dict_with_value[horizon])
        with open(self.soil_ht_path, 'w') as file:
            for item in new_value_to_write:
                file.write(f"{item}\n")

    def write_soil_node_to_dat(self, node_list):
        head, end = self.line_of_soil_node()
        node_list_string = []
        dat_data = self.dat_data
        for count, node in enumerate(range(0, len(node_list))):
            if count == 0:
                node_list_string.append(str(len(node_list)))
                node_list_string.append('{}  {}  {}  '.format(str(node_list[count][0] + 1),
                                                              str(node_list[count][1]),
                                                              str(node_list[count][2])))
            else:
                node_list_string.append('{}  {}  {}  '.format(str(node_list[count][0] + 1),
                                                              str(node_list[count][1]),
                                                              str(node_list[count][2])))
        # replace the dat data with the new node list
        dat_data[head - 1:end + 1] = node_list_string
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_soil_horizon_depth_to_dat(self, new_horizon_list):
        str_new_horizon_list = []
        head, end = self.line_of_soil_physical_depth()
        dat_data = self.dat_data
        for count, horizon in enumerate(new_horizon_list):
            if count == 0:
                str_new_horizon_list.append('{}  {}'.format(str(len(new_horizon_list)), str(new_horizon_list[-1])))
                str_new_horizon_list.append(str(new_horizon_list[count]))
            else:
                str_new_horizon_list.append(str(new_horizon_list[count]))
        dat_data[head:end + 1] = str_new_horizon_list
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_new_soil_heat_properties_to_dat(self, soil_heat_property_dict):
        head, end = self.line_of_soil_heat_properties()
        new_str_list = []
        for key in soil_heat_property_dict:
            new_str_list.append(soil_heat_property_dict[key])
        dat_data = self.dat_data
        dat_data[head:end + 1] = new_str_list
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_new_soil_micropore_to_dat(self, soil_micropore_dict):
        head, end = self.line_of_soil_micropore()
        new_str_list = []
        for key in soil_micropore_dict:
            new_str_list.append(soil_micropore_dict[key])
        dat_data = self.dat_data
        dat_data[head:end + 1] = new_str_list
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_new_soil_macropore_to_dat(self, soil_macropore_dict):
        head, end = self.line_of_soil_micropore()
        new_str_list = []
        for key in soil_macropore_dict:
            new_str_list.append(soil_macropore_dict[key])
        dat_data = self.dat_data
        dat_data[head:end + 1] = new_str_list
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_new_soil_infiltration_to_dat(self, infiltration_properties):
        head, end = self.line_of_soil_infiltration()
        new_string = '{}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  {}  '.format(
            infiltration_properties.surface_crust_present, infiltration_properties.crust_hydraulic_conductivity,
            infiltration_properties.bottom_boundry_condition,
            infiltration_properties.Field_saturation_fraction, infiltration_properties.Convergence_Criteria,
            infiltration_properties.Maximum_number_of_iterations,
            infiltration_properties.Maximum_number_of_cycles,
            infiltration_properties.Management_cutoff_threshold_for_soil_moisture_content,
            infiltration_properties.Perched_water_table, infiltration_properties.water_table_leakage_rate,
            infiltration_properties.Drains_are_present, infiltration_properties.depth_from_surface_to_drains,
            infiltration_properties.drain_spacing, infiltration_properties.radius_of_drain,
            infiltration_properties.Init_gradient_flow, infiltration_properties.Lateral_hydraulic_gradient,
            infiltration_properties.Minimum_water_suction_head,
            infiltration_properties.Field_Capacity_water_suction_head,
            infiltration_properties.Wilting_Point_water_suction_head)

        dat_data = self.dat_data
        print(dat_data[end])
        dat_data[end] = new_string
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_new_soil_micropore_properties_to_dat(self, soil_micropore_dict):
        str_new_horizon_list = []
        head, end = self.line_of_soil_micropore()
        dat_data = self.dat_data
        for count, horizon in enumerate(soil_micropore_dict):
            if count == 0:
                str_new_horizon_list.append('0  1.0  4.4  ')
                str_new_horizon_list.append(str(soil_micropore_dict[horizon]))
            else:
                str_new_horizon_list.append(str(soil_micropore_dict[horizon]))
        dat_data[head:end + 1] = str_new_horizon_list
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_new_soil_macropore_properties_to_dat(self, soil_macropore_dict, soil_macropore_properties):
        new_horizon_list = []
        head, end = self.line_of_soil_macropore()
        dat_data = self.dat_data
        new_horizon_list.append('{}  {}  {}  '.format(soil_macropore_properties.macropores_present,
                                                      soil_macropore_properties.sorptivity_factor
                                                      , soil_macropore_properties.tile_drain_express))
        new_horizon_list.append(
            '{}  {}'.format(soil_macropore_properties.radial_holes, soil_macropore_properties.cracks_columns))
        for layer in soil_macropore_dict:
            layer_info = soil_macropore_dict[layer]
            new_horizon_list.append(
                '{}  {}  {}  {}  {}  {}  '.format(layer_info.total_macroporosity, layer_info.average_radius,
                                                  layer_info.width, layer_info.crack_length,
                                                  layer_info.length_of_aggregate,
                                                  layer_info.fraction_of_dead_end))
        dat_data[head:end + 1] = new_horizon_list
        with open(self.dat_path, 'w', encoding='ISO-8859-1') as file:
            for line in dat_data:
                file.write(line + '\n')

    ##### place holder for now, directly taking the existing data
    def write_new_soil_init_nutrient(self, number_of_layers):
        head, end = self.line_of_init_soil_nutrient_number()
        dat_data = self.init_data
        place_holder_list = [
            '74.1  14.5  243.8  1910.8  10000.0  0.0  477086.9  7484.5  67000.0  0.0  0.5  0.1  0.0  0.0  0.0  0.0  0.0  4.0',
            '74.1  14.5  243.8  1910.8  10000.0  0.0  477086.9  7484.5  67000.0  0.0  0.5  0.1  0.0  0.0  0.0  0.0  0.0  4.0 ',
            '13.7  42.4  172.7  1839.4  8502.4  0.0  116475.7  1466.3  13000.0  0.0  0.5  0.1  0.0  0.0  0.0  0.0  0.0  4.0',
            '9.5  23.7  121.3  1273.9  5901.6  0.0  99000.0  1247.3  11000.0  0.0  0.596  0.1  0.0  0.0  0.0  0.0  0.0  4.0 ']
        # Extend to match horizon count
        while len(place_holder_list) < len(number_of_layers):
            place_holder_list.append(place_holder_list[-1])
        # Trim to match horizon count
        new_list = place_holder_list[:len(number_of_layers)]

        dat_data[head:end + 1] = new_list

        with open(self.init_path, 'w') as file:
            for line in dat_data:
                file.write(line + '\n')

    ##### place holder for now, directly taking the existing data
    def write_new_soil_init_chemistry(self, number_of_layers):
        head, end = self.line_of_init_soil_chemistry()
        dat_data = self.init_data
        place_holder_dict = {1:['6.91   T  F  F 0.000275  20.1  0.0  0.0  0.0  0.0  0.0  0.07  ',
                               '43.67  46.43  9.0  3.45  200.3',
                                '3.448  0.0  0.0 '],
                             2:['6.91   T  F  F 0.000275  20.1  0.0  0.0  0.0  0.0  0.0  0.07',
                                '43.67  46.43  9.0  3.45  200.3  ',
                                '3.448  0.0  0.0  '],
                             3: ['6.87   T  F  F 0.000275  20.1  0.0  0.0  0.0  0.0  0.0  0.07',
                                 '34.73  49.4  6.233  3.357  179.0  ',
                                 '3.356  0.0  0.0  '],
                             4: ['7.01   T  F  F 0.00025  30.1  0.0  0.0  0.0  0.0  0.0  0.07 ',
                                 '32.47  43.8  4.467  3.313  211.0  ',
                                 '3.311  0.0  0.0  ']
                             }
        if len(number_of_layers) > len(list(place_holder_dict.keys())):
            dif = (len(number_of_layers)) - len(list(place_holder_dict.keys()))
            for num in range(0, dif):
                place_holder_dict[num+5] = place_holder_dict[4]
        if len(number_of_layers) < len(list(place_holder_dict.keys())):
            for num in list(place_holder_dict.keys()):
                if num not in range(1, len(number_of_layers) + 1):
                    place_holder_dict.pop(num)

        new_list = []
        for key in range(1, max(list(place_holder_dict.keys()))+1):
            lines = place_holder_dict[key]
            for each_line in lines:
                    new_list.append(each_line)

        dat_data[head:end + 1] = new_list

        with open(self.init_path, 'w') as file:
            for line in dat_data:
                file.write(line + '\n')

    def write_new_soil_init_water_and_temp(self, number_of_layers):
        # first line are flags, setting to tensio first
        head, end = self.line_of_init_soil_water_and_temp()
        dat_data = self.init_data
        new_list = ['0 0']
        for count, layer in enumerate(number_of_layers):
            if count == len(number_of_layers)-1:
                new_list.append('0.0 15.0')
            else:
                tensio = str(round(float((len(number_of_layers)-1-count)*(-10)), 1))
                new_list.append(f'{tensio} 10.0')

        dat_data[head:end + 1] = new_list

        with open(self.init_path, 'w') as file:
            for line in dat_data:
                file.write(line + '\n')


    def generate_node_data(self, soil_horizon_list):
        dict_with_node_and_distance = []
        depth, distance = nlayer_gen(len(soil_horizon_list), soil_horizon_list)
        for count, each_depth in enumerate(depth):
            if each_depth <= soil_horizon_list[-1]:
                dict_with_node_and_distance.append([count, each_depth, distance[count]])
            else:
                break
        return dict_with_node_and_distance

    # parse the ana file
    def rzwqm_res_parse(self, var_name):
        # this function is to parse the rzwqm result, and return only the required column as list
        # should have a list for corresponding var's column number
        # for snow, it should be 91
        if var_name == 'snow':
            column_num = 91
        elif var_name == 'tile_drainage':
            column_num = 10
        julien_day_col = 0
        lines = self.read_text_file(self.simulate_path)
        del lines[0]
        # result starts at index #23
        lines = lines[23:]
        desired_data = {}

        for line in lines:
            try:
                if var_name == 'tile_drainage':
                    # output drainage volume in mm
                    desired_data[datetime.strptime(line[julien_day_col], '%Y.%j')] = float((line[column_num])) * 10
                else:
                    desired_data[datetime.strptime(line[julien_day_col], '%Y.%j')] = float((line[column_num]))
            except Exception as e:
                print(e)
                year = line[julien_day_col].split('.')[0]
                if var_name == 'tile_drainage':
                    # output drainage volume in mm:
                    desired_data[datetime.strptime(year + '.' + '001', '%j%Y')] = float(
                        (line[column_num])) * 10
                else:
                    desired_data[datetime.strptime(year + '.' + '001', '%j%Y')] = float(
                        (line[column_num]))

        return desired_data

    # parse the met file
    def rzwqm_met_parse(self):
        # this function parses the met file
        head = self.met_data[0:36]
        content = self.met_data[36:]
        parsed_content = []
        for line in content:
            split_line = line.split()
            parsed_content.append(split_line)
        return {'head': head, 'parsed_content': parsed_content}

    def rzwqm_return_precipitation(self):
        precipitation_dict = {}
        lines = self.rzwqm_met_parse()['parsed_content']

        for line in lines:
            try:
                precipitation_dict[datetime.strptime(line[0] + line[1], '%j%Y')] = float(line[9])
            except Exception as e:
                continue

        return precipitation_dict

    def rzwqm_met_quality_check(self):
        parsed_met = self.rzwqm_met_parse()
        # for each line, [0] is day, [1] is year, [2] is Tmin, [3] is Tmax,
        # [4] is U, [5] is Rad, [6] is E-pan, [7] is RH, [8] is Par, [9] is Rain
        for line in parsed_met['parsed_content']:
            # check if tmin is less than tmax:
            if float(line[2]) > float(line[3]):
                # switch the tmin and tmax
                tmin = line[3]
                tmax = line[2]
                line[3] = str(tmax)
                line[2] = str(tmin)
            # check RH:
            if float(line[7]) > 100:
                line[7] = '100'
        write_to_rzwqm_met(self.met_path, parsed_met['parsed_content'],
                           parsed_met['head'])

    # write to the met file
    @staticmethod
    def rzwqm_met_modify(new_var_list, parsed_content):
        new_met_now = parsed_content['parsed_content']
        for data in new_var_list:
            for count, og_data in enumerate(new_met_now):
                fmt = '%Y%j'
                jdate = og_data[1] + og_data[0]
                og_date = datetime.strptime(jdate, fmt)
                if data['date'].date() == og_date.date():
                    if float(new_met_now[count][9]) == 0:
                        # print(f"new rain is {data['new_value']}, and old rain is {new_met_now[count][9]}")
                        new_met_now[count][9] = data['new_value']
                        break
        parsed_content['parsed_content'] = new_met_now
        return parsed_content

    @staticmethod
    def rzwqm_met_tweak(data_list, parsed_content, index, condition, fmt, snow_i=None):
        del data_list[0]
        new_met_now = parsed_content['parsed_content']
        c_dates = []
        for data in data_list:
            c_date = datetime.strptime(data['date'], fmt)
            c_dates.append({c_date: data['observed'], 'dif': data['dif']})

        for c_date in c_dates:
            for count, og_data in enumerate(new_met_now):
                fmt_og = '%Y%j'
                jdate = og_data[1] + og_data[0]
                og_date = datetime.strptime(jdate, fmt_og)
                if list(c_date.keys())[0].date() == og_date.date():
                    val = float(new_met_now[count][9])
                    prev_val = float(new_met_now[count - 1][9])
                    if snow_i:
                        if c_date['dif'] == 100:
                            new_met_now[count][9] = list(c_date.values())[0] * snow_i
                            if not og_date - timedelta(days=1) in c_dates:
                                new_met_now[count - 1][9] = list(c_date.values())[0] * snow_i
                    elif condition == 'less' and c_date['dif'] != 100:
                        new_met_now[count][9] = val * index
                        if not og_date - timedelta(days=1) in c_dates:
                            new_met_now[count - 1][9] = prev_val / index
                    elif condition == 'over':
                        new_met_now[count][9] = val * index
                        if not og_date - timedelta(days=1) in c_dates:
                            new_met_now[count - 1][9] = prev_val * index
                    break

        parsed_content['parsed_content'] = new_met_now
        return parsed_content

    def rzwqm_general_text_parse(self, out_file_name, head_end):
        path = os.path.join(self.rzwqm_project_path, out_file_name)
        with open(path) as f:
            lines = [line.rstrip('\n') for line in f]
        head = lines[0:head_end]
        content = lines[head_end:]
        parsed_content = []
        for line in content:
            split_line = line.split()
            parsed_content.append(split_line)
        return {'head': head, 'parsed_content': parsed_content}

    @staticmethod
    def change_param_val_in_one_line(columns_with_val, line):
        changed = line.split()
        for val in columns_with_val.keys():
            changed[val] = columns_with_val[val]
        return changed

    # this is to parse the layer.plt file, mainly for soil temperature for now. 09/30/22
    @staticmethod
    def rzwqm_parse_layer(desired_depth, file, head_end, column_num):
        # desired_dates = return_layer_date_count('2000-01-01', '2005-12-31', 11, 4, '%Y-%m-%d')
        content = file[head_end:]
        parsed_content = []
        for line in content:
            split_line = line.split()
            parsed_content.append(split_line)
        return_obj = {}
        for data in parsed_content:
            # the_depth is the depth from the layer.plt file
            the_depth = int(float(data[1]))
            # organize the soil temperature based on nodes
            if the_depth in desired_depth:
                try:
                    if return_obj[the_depth]:
                        return_obj[the_depth].append(float(data[column_num]))
                except Exception as e:
                    return_obj[the_depth] = []
                    return_obj[the_depth].append(float(data[column_num]))
        return return_obj

    # the function returns the nodes descritized by RZWQM in a list
    def parse_soil_discretization_nodes(self):
        soil_nodes_head_identifier = '=       record (depth increasing with node no.)'
        soil_nodes_end_identifier = '=         SOIL HORIZON PHYSICAL PROPERTIES'
        lines = find_desired_line_numbers(soil_nodes_head_identifier, soil_nodes_end_identifier,
                                          self.dat_data, 3, 2)
        nodes = []
        for num in range(lines[0], lines[1] + 1):
            line = self.dat_data[num].split()
            depth = int(float(line[1]))
            nodes.append(depth)
        return nodes

    def return_soil_nodes(self):
        head, end = self.line_of_soil_node()
        soil_horizons = self.return_soil_layer_depth_dict()
        node_lines = {}
        for node in range(head, end + 1):
            split_node = self.dat_data[node].split()
            node_lines[int(split_node[0])] = float(split_node[1])
        soil_nodes = {}
        last_horizon_depth = 0
        for horizon in soil_horizons:
            temp_list = []
            for node in node_lines:
                if last_horizon_depth < node_lines[node] < soil_horizons[horizon]:
                    temp_list.append(node)
                elif node_lines[node] == soil_horizons[horizon]:
                    temp_list.append(node)
                    last_horizon_depth = soil_horizons[horizon]
                    break

            soil_nodes[horizon] = temp_list
        return soil_nodes

    def insert_new_horizon_to_existing_dat_file(self, new_horizon_list):
        new_node = self.generate_node_data(new_horizon_list)
        self.write_soil_horizon_depth_to_dat(new_horizon_list)
        self.write_soil_node_to_dat(new_node)

    def return_soil_temperature(self, column_num):
        head_line = find_desired_line_numbers(
            '****************** DATA STARTS HERE *****************',
            '', self.layer_data, 1, 1)[0]
        soil_temp = self.rzwqm_parse_layer(self.parse_soil_discretization_nodes(),
                                           self.layer_data, head_line, column_num)
        return soil_temp

    def dates_value_dict_gen(self, value_list):
        returing_dict = {}
        starting_date, ending_date = self.scenario_start_end_date
        dates_list = loop_between_dates(starting_date, ending_date)

        for count, date_each_day in enumerate(dates_list):
            try:
                returing_dict[date_each_day] = value_list[count]
            except IndexError as e:
                break
        return returing_dict

    def line_number_of_soil_hydraulic(self):
        head, end = find_desired_line_numbers(soil_hydraulic_properties_identifier['head'],
                                              soil_hydraulic_properties_identifier['end'], self.dat_data, 2, 2)
        return head, end

    def line_number_of_snow_param(self):
        head, end = find_desired_line_numbers(albedo_identifier['head'],
                                              albedo_identifier['end'], self.dat_data, 2, 2)
        return head, end

    def line_number_of_env_prop(self):
        head, end = find_desired_line_numbers(snow_identifier['head'],
                                              snow_identifier['end'], self.sno_data, 3, 3)
        return head, end

    def line_number_of_soil_temperature(self):
        headline_number = find_desired_line_numbers('****************** DATA STARTS HERE *****************', '',
                                                    self.layer_data, 1, 1)[0]
        return headline_number, len(self.layer_data)

    def line_of_soil_physical_depth(self):
        head, end = find_desired_line_numbers(soil_physical_identifer['head'], soil_physical_identifer['end'],
                                              self.dat_data, 2, 3)
        return head, end

    def line_of_soil_physical_properties(self):
        head, end = find_desired_line_numbers(soil_physical_properties_identifer['head'],
                                              soil_physical_properties_identifer['end'],
                                              self.dat_data, 2, 2)
        return head, end

    def line_of_soil_node(self):
        head, end = find_desired_line_numbers(soil_node_identifier['head'],
                                              soil_node_identifier['end'],
                                              self.dat_data, 3, 2)
        return head, end

    def line_of_soil_heat_properties(self):
        head, end = find_desired_line_numbers(soil_heat_model_parameter_identifier['head'],
                                              soil_heat_model_parameter_identifier['end'],
                                              self.dat_data, 2, 3)
        return head, end

    def line_of_soil_infiltration(self):
        head, end = find_desired_line_numbers(soil_infiltration_parameter_identifier['head'],
                                              soil_infiltration_parameter_identifier['end'],
                                              self.dat_data, 2, 3)
        return head, end

    def line_of_soil_micropore(self):
        head, end = find_desired_line_numbers(soil_micropore_parameter_identifier['head'],
                                              soil_micropore_parameter_identifier['end'],
                                              self.dat_data, 2, 3)
        return head, end

    def line_of_soil_macropore(self):
        head, end = find_desired_line_numbers(soil_macropore_parameter_identifier['head'],
                                              soil_macropore_parameter_identifier['end'],
                                              self.dat_data, 2, 3)
        return head, end

    def line_of_grid_general_properties(self):
        head, end = find_desired_line_numbers(grid_general_property_identifier['head'],
                                              grid_general_property_identifier['end'],
                                              self.dat_data, 2, 3)
        return head, end

    def line_of_init_soil_nutrient_number(self):
        head, end = find_desired_line_numbers(rz_init_soil_nutrient_identifer['head'],
                                              rz_init_soil_nutrient_identifer['end'],
                                              self.init_data, 2, 2)
        return head, end

    def line_of_init_soil_chemistry(self):
        head, end = find_desired_line_numbers(rz_init_soil_chemistry_identifer['head'],
                                              rz_init_soil_chemistry_identifer['end'],
                                              self.init_data, 2, 2)
        return head, end

    def line_of_init_soil_water_and_temp(self):
        head, end = find_desired_line_numbers(rz_init_water_identifer['head'],
                                              rz_init_water_identifer['end'],
                                              self.init_data, 2, 2)
        return head, end



    @sno_path.setter
    def sno_path(self, value):
        self._sno_path = value

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

    def return_date_time_dict_for_met_variable(self, var_position):
        returning_datetime_object = {}
        for line in self.rzwqm_met_parse()['parsed_content']:
            returning_datetime_object[datetime.strptime(line[0] + line[1], '%j%Y')] = float(line[var_position])
        return returning_datetime_object

    def update_rain_input_larger_value(self, updated_rain, month_list=None):
        parsed_met = self.rzwqm_met_parse()
        for line in parsed_met['parsed_content']:
            if updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')] != '':
                # if month list is provided, then only certain months data are updating
                if month_list is not None:
                    if is_datetime_in_months(datetime.strptime(line[0] + line[1], '%j%Y'), month_list):
                        if updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')] > float(line[9]):
                            line[9] = updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')]
                else:
                    if updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')] > float(line[9]):
                        line[9] = updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')]
        write_to_rzwqm_met(self.met_path, parsed_met['parsed_content'],
                           parsed_met['head'])

    def update_rain_input(self, updated_rain, month_list=None):
        parsed_met = self.rzwqm_met_parse()
        for line in parsed_met['parsed_content']:
            try:
                if updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')] !='':
                    # if month list is provided, then only certain months data are updating
                    if month_list is not None:
                        if is_datetime_in_months(datetime.strptime(line[0] + line[1], '%j%Y'), month_list):
                            line[9] = round(updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')], 2)
                    else:
                        line[9] = round(updated_rain[datetime.strptime(line[0] + line[1], '%j%Y')], 2)
            except KeyError as e:
                continue

        write_to_rzwqm_met(self.met_path, parsed_met['parsed_content'],
                           parsed_met['head'])

    def return_date_time_turple_for_met_variable(self, var_position):
        returning_datetime_object = []
        for line in self.rzwqm_met_parse()['parsed_content']:
            returning_datetime_object.append((datetime.strptime(line[0] + line[1], '%j%Y'), float(line[var_position])))
        return returning_datetime_object

    def create_breakpoint_file(self) -> None:
        """
            Create a breakpoint rainfall file (.brk) from daily precipitation data.

            Args:
            - daily_precipitation (dict): A dictionary with datetime.date objects as keys and daily precipitation as values.
            - output_filename (str): The name of the output file.

            Returns:
            - None: Writes the breakpoint data to the specified file.
            """
        rain_date_time_data = self.return_date_time_turple_for_met_variable(9)
        # Define the header string
        header = ['===============================================================================',
                  '=',
                  '=                         R Z W Q M 2',
                  '=           User created breakpoint rainfall file from daily met file',
                  '=',
                  '=',
                  '==       B R E A K P O I N T  R A I N F A L L   D A T A',
                  '==',
                  '== Rec 1: calendar code: =1 - date counted as Julian days within year',
                  '== Rec 2: control info for a breakpoint event:',
                  '==        year, date, no. breakpoints, midnight (day spanning, 1=yes)',
                  '==        code, total storm depth [in]',
                  '== Rec 3: pairs of cum storm dep [in] & clock time [min]',
                  '==        5 pairs per rec',
                  '== REPEAT Rec 3 to complete data for an event',
                  '==',
                  "== REPEAT Rec's 2 & 3 for subsequent events",
                  '=',
                  '===============================================================================',
                  '1']

        # Write the data to the file
        with open(self.brk_path, 'w') as file:
            for line in header:
                file.write(line + '\n')
            for date, precip in rain_date_time_data:
                if precip > 0:
                    precip = precip / 25.4
                    # Calculate the clock time based on the example values given
                    if precip * 1500 > 120:
                        clock_time = 120
                    else:
                        clock_time = int(precip * 1500)  # This is a rough estimate based on the example

                    # Write the control info for the breakpoint event
                    file.write(
                        f"    {date.year}       {date.timetuple().tm_yday}        2        0     {precip:.3f}\n")
                    # Write the data for the event
                    file.write(f"    0.000        0     {precip:.3f}        {clock_time}\n")

        return None


def rzwqm_scenario_mass_generation(all_stations, original_scenario_path,
                                   soil_db_shapefile_path, soil_cmp_path, soil_layer_path, land_cover_map_path,
                                   province,
                                   particle_density, N1, constant_for_oh, use_default_value, original_scenario_name,
                                   extend_horizon_depth, soil_macropore_general_prop, soil_infiltration_properties,
                                   warm_up_period, scen_gen=False,
                                   meteo_gen=False, soil_gen=False, station_meta_value_update=True,
                                   grid_general_info_update=False, rz_init_update=False):
    station_id_dict = {}
    for station in all_stations:
        try:
            station_id = str(station[0])
            lat = station[1]
            lon = station[2]
            station_id_dict[station_id] = (lat, lon)
            if len(station) == 3:
                end, start  = return_start_and_end_each_station(station_id)[0]
            elif len(station) > 3:
                start, end = station[3], station[4]
            # warm up period is inputted as number of years
            start = start - relativedelta(years=warm_up_period)
            if scen_gen:
                # use soil temperature duration for now, later on should be in station meta for each province
                initialize_scneario_based_on_existing(original_scenario_path, original_scenario_name, str(station_id),
                                                      True,
                                                      (start, end), True)
            rz = RZWQM(original_scenario_path, station_id)
            # generate met file for each grid/station/location
            if meteo_gen:
                if province == 'Manitoba':
                    met_mani = Manitoba_data_retrieve(station_id, start.strftime(input_date_format),
                                                      end.strftime(input_date_format), lat, lon, 100)
                    met_file_mani = met_mani.final_met_data_for_rz()
                    met_head = generate_rzwqm_met_header(start, end)
                    write_to_rzwqm_met(rz.met_path, met_file_mani, met_head)
                    rz.create_breakpoint_file()

        except Exception as e:
            print(e)
            print(str(station[0]) + ' has error downloading data or snow depth is not available')
    if soil_gen:
        # reading dbf and shapefile is time consuming, thus operations for each location are performed together
        original_soil_properties_dict = canada_soil_db_retrieve(soil_db_shapefile_path, soil_cmp_path, soil_layer_path,
                                                       land_cover_map_path,
                                                       station_id_dict)

        if len(original_soil_properties_dict[1]) == 0:
            print('All soil properties had been found')
        else:
            print('some stations soil properties were not found and they are:')
            if station_meta_value_update:
                for station_id in original_soil_properties_dict[1]:
                    add_station_meta_value(station_id, 'soil_properties_exist', 0)

        soil_properties_dict = original_soil_properties_dict[0]
        soil_attribute_dict = original_soil_properties_dict[2]
        # filter out 0 and smaller layers in the returned soil properties if a layer does not have enough layers
        # after the filtration, then it will be updated as no soil properties as well
        for each_station in list(soil_properties_dict.keys()):
            soil_properties_dict[each_station] = filter_by_ldepth(soil_properties_dict[each_station])
            soil_properties_dict[each_station] = filter_by_clay(soil_properties_dict[each_station])
            if station_meta_value_update:
                if len(list(soil_properties_dict[each_station]['LDEPTH'])) == 0:
                    add_station_meta_value(each_station, 'soil_properties_exist', 0)
                    soil_properties_dict.pop(each_station)
                else:
                    add_station_meta_value(each_station, 'soil_properties_exist', 1)

        # iterate through the key of the soil_properties dict to generate the soil properties in dat file and met files
        for key in soil_properties_dict:
            # create rz class based on the key
            rz = RZWQM(original_scenario_path, str(key))

            #### write soil physical properties###########################################################################
            horizon_depth = list(soil_properties_dict[key]['LDEPTH'])
            horizon_depth_new = horizon_depth.copy()
            if horizon_depth[-1] < extend_horizon_depth:
                horizon_depth_new.append(extend_horizon_depth)
            rz.insert_new_horizon_to_existing_dat_file(horizon_depth_new)
            sand = list(soil_properties_dict[key]['TSAND'])
            silt = list(soil_properties_dict[key]['TSILT'])
            clay = list(soil_properties_dict[key]['TCLAY'])

            organic_carbon = list(soil_properties_dict[key]['ORGCARB'])
            bulk_density = list(soil_properties_dict[key]['BD'])
            soil_physical_prop_dict = {}
            if horizon_depth[-1] >= extend_horizon_depth:
                for layer_number in range(0, len(sand)):
                    soil_physical_prop_dict[layer_number + 1] = soil_physical_properties_each_horizon(
                        bulk_density[layer_number],
                        particle_density,  # set particle density as 2.65 as default
                        sand[layer_number] * 0.01,
                        silt[layer_number] * 0.01,
                        clay[layer_number] * 0.01)
            else:
                for layer_number in range(0, len(sand) + 1):
                    # set the extended horizon equal to the last available physical propertyz
                    if layer_number == len(sand):
                        soil_physical_prop_dict[layer_number + 1] = soil_physical_properties_each_horizon(
                            bulk_density[layer_number - 1],
                            particle_density,  # set particle density as 2.65 as default
                            sand[layer_number - 1] * 0.01,
                            silt[layer_number - 1] * 0.01,
                            clay[layer_number - 1] * 0.01)
                    else:
                        soil_physical_prop_dict[layer_number + 1] = soil_physical_properties_each_horizon(
                            bulk_density[layer_number],
                            particle_density,  # set particle density as 2.65 as default
                            sand[layer_number] * 0.01,
                            silt[layer_number] * 0.01,
                            clay[layer_number] * 0.01)
            rz.write_new_soil_physical_properties_to_dat(soil_physical_prop_dict)

            #### write soil hydraulic properties###########################################################################
            soil_hydraulic_prop_dict = {}
            KSAT = list(soil_properties_dict[key]['KSAT'])
            KP0 = [round(x * 0.01, 2) for x in list(soil_properties_dict[key]['KP0'])]
            KP10 = [round(x * 0.01, 2) for x in list(soil_properties_dict[key]['KP10'])]
            KP33 = [round(x * 0.01, 2) for x in list(soil_properties_dict[key]['KP33'])]
            KP1500 = [round(x * 0.01, 2) for x in list(soil_properties_dict[key]['KP1500'])]

            for layer_number in range(0, len(horizon_depth_new)):
                actual_layer_number = layer_number
                if layer_number >= len(KP33):
                    layer_number = layer_number - 1

                default_value_for_the_layer = soil_default_setter(
                    soil_texture_setter(soil_physical_prop_dict[layer_number + 1].sand,
                                        soil_physical_prop_dict[layer_number + 1].clay))
                if use_default_value == False:
                    # if measured of fc33 and fc15 is available, estimate pore size dist and bubbling pressure
                    if KP33[layer_number] and KP1500[layer_number]:
                        pore_size_dist = pore_size_distribution_estimate(KP33[layer_number], KP1500[layer_number],
                                                                         default_value_for_the_layer['wr'])
                    else:
                        pore_size_dist = default_value_for_the_layer['pore_size_dist']
                    # similarly if saturated water content available:
                    if KP0[layer_number] and KP33[layer_number]:
                        B = B_estimate(KP33[layer_number], default_value_for_the_layer['wr'], pore_size_dist)
                        bubbling_pressure = bubbling_pressure_estimate(KP0[layer_number], pore_size_dist,
                                                                       default_value_for_the_layer['wr'], B)
                    else:
                        B = B_estimate(default_value_for_the_layer['fc33'], default_value_for_the_layer['wr'],
                                       pore_size_dist)
                        bubbling_pressure = default_value_for_the_layer['bubbling_pressure']
                    if KSAT[layer_number]:
                        C2 = C2_estimate(bubbling_pressure, pore_size_dist, KSAT[layer_number], N1)
                    else:
                        C2 = C2_estimate(bubbling_pressure, pore_size_dist, default_value_for_the_layer['ksat'], N1)
                    N2 = N2_estimate(pore_size_dist)
                    soil_hydraulic_prop_dict[actual_layer_number] = soil_hydraulic_properties_each_horizon(
                        round(pore_size_dist, 2),
                        KP0[layer_number],
                        default_value_for_the_layer['wr'],
                        round(bubbling_pressure, 2),
                        constant_for_oh,
                        KSAT[layer_number],
                        KSAT[layer_number],
                        round(N2, 2), round(C2, 2),
                        layer_number + 1,
                        KP33[
                            layer_number],
                        KP10[
                            layer_number],
                        KP1500[
                            layer_number])
                else:
                    bubbling_pressure = default_value_for_the_layer['bubbling_pressure']
                    pore_size_dist = default_value_for_the_layer['pore_size_dist']
                    ws = default_value_for_the_layer['ws']
                    wr = default_value_for_the_layer['wr']
                    fc33 = default_value_for_the_layer['fc33']
                    fc15 = default_value_for_the_layer['fc15']
                    ksat = default_value_for_the_layer['ksat']
                    fc10 = fc10_estimate(ws, wr, bubbling_pressure, pore_size_dist)
                    C2 = C2_estimate(bubbling_pressure, pore_size_dist, ksat, N1)
                    N2 = N2_estimate(pore_size_dist)
                    soil_hydraulic_prop_dict[actual_layer_number] = soil_hydraulic_properties_each_horizon(
                        pore_size_dist,
                        ws, wr,
                        bubbling_pressure,
                        constant_for_oh,
                        ksat,
                        ksat,
                        N2, C2,
                        layer_number + 1,
                        fc33, fc10, fc15)
            rz.write_new_hydraulic_properties_to_dat(soil_hydraulic_prop_dict)

            #### write soil heat properties##############################################################################
            soil_heat_prop_dict = {}
            for layer_number in range(0, len(horizon_depth_new)):
                actual_layer_number = layer_number
                if layer_number >= len(KP33):
                    layer_number = layer_number - 1
                soil_heat_prop_dict[actual_layer_number] = '2  0.00111  '
            rz.write_new_soil_heat_properties_to_dat(soil_heat_prop_dict)

            #### write soil micropore properties############################################################################
            soil_micropore_prop_dict = {}
            for layer_number in range(0, len(horizon_depth_new)):
                actual_layer_number = layer_number
                if layer_number >= len(KP33):
                    layer_number = layer_number - 1
                texture = soil_texture_setter(soil_physical_prop_dict[layer_number + 1].sand,
                                              soil_physical_prop_dict[layer_number + 1].clay)
                soil_micropore_prop_dict[actual_layer_number] = default_microporosity_for_each_soil_type(texture)
            rz.write_new_soil_micropore_properties_to_dat(soil_micropore_prop_dict)

            #### write soil macropore properties############################################################################
            soil_macropore_prop_dict = {}
            for layer_number in range(0, len(horizon_depth_new)):
                actual_layer_number = layer_number
                if layer_number >= len(KP33):
                    layer_number = layer_number - 1
                soil_macropore_prop_dict[actual_layer_number] = soil_macropore_properties_each_horizon(
                    0.01, 0.0, 0.05, 10.0, 10.0, 0.5)
            rz.write_new_soil_macropore_properties_to_dat(soil_macropore_prop_dict, soil_macropore_general_prop)

            #### write soil infiltration properties#########################################################################
            rz.write_new_soil_infiltration_to_dat(soil_infiltration_properties)

            #### write new soil rz_init properties##########################################################################

            if grid_general_info_update:
                # currenlty only updating the slope of the soil, adding the soil area function later if needed
                slope = soil_attribute_dict[key]['slope']
                grid_property = rz.return_soil_general_properties()
                setattr(grid_property, 'slope', slope)
                lat = round(select_one_value_from_a_col_with_condition('manitoba_meteo', 'lat','station_meta','station_id', key)[0] * (math.pi / 180), 5)
                lon = round(select_one_value_from_a_col_with_condition('manitoba_meteo', 'lon', 'station_meta', 'station_id', key)[0]* (math.pi / 180), 5)
                setattr(grid_property, 'center_lat', lat)
                setattr(grid_property, 'center_lon', lon)
                rz.write_soil_general_properties_to_dat(grid_property)

            if rz_init_update:
                rz.write_new_soil_init_water_and_temp(horizon_depth_new)
                rz.write_new_soil_init_chemistry(horizon_depth_new)
                rz.write_new_soil_init_nutrient(horizon_depth_new)

def mass_updating_ipnames_directory(new_root_directory, project_directory, stationorgrid_id_list):
    for stationorgrid_id in stationorgrid_id_list:
        stationorgrid_id = str(stationorgrid_id)
        rz = RZWQM(project_directory, stationorgrid_id)
        ip = rz.ipnames
        ip[0] = new_root_directory + stationorgrid_id + "//cntrl.dat"
        ip[1] = new_root_directory + stationorgrid_id + "//rzwqm.dat"
        ip[4] = new_root_directory + stationorgrid_id + "//rzinit.dat"
        ip[5] = new_root_directory + stationorgrid_id + "//plgen.dat"
        ip[6] = new_root_directory + 'Meteorology//' + stationorgrid_id + '.sno'
        ip[2] = new_root_directory + 'Meteorology//' + stationorgrid_id + '.met'
        ip[3] = new_root_directory + 'Meteorology//' + stationorgrid_id + '.brk'
        ip[7] = new_root_directory + "Analysis" + "//" + stationorgrid_id + ".ana"

        with open(rz.ipnames_path, 'w') as file:
            for line in ip:
                file.write(line + '\n')

if __name__ == '__main__':
    # scenario creation
    # layers = [15, 20, 100]
    # nlayer_gen(len(layers), layers)
    root = 'C://'
    all_manitoba_stations = select_all_from_multi_col(['station_id', 'lat', 'lon'], 'station_meta')
    # all_manitoba_stations = [(252, 50.70, -97.50)]
    # all_manitoba_stations = [('kentville', 45.073151, -64.513866, datetime.strptime('2001-01-01', input_date_format),
    #                           datetime.strptime('2020-12-31', input_date_format))]

    stations = [x for x in all_manitoba_stations if int(x[0]) <243]
    # mass_updating_ipnames_directory('/home/ubuntu/projects_linux/', original_scenario_path, stations)
    original_scenario_path = root + 'RZWQM2//projects//'
    land_cover_map_path = 'soil_type/landcover-2020-classification.tif'

    # # first position
    shape_file_dict = {
        'Manitoba': {'shapefile': 'soil_type\\dss_v3_mb_20161207\\dss_v3_mb.shp',
                     'cmp': 'soil_type\\dss_v3_mb_20161207\\dss_v3_mb_cmp.dbf',
                     'soil_layer': 'soil_type\\dss_v3_mb_20161207\\soil_layer_mb_v2.dbf',
                     'prt': 'soil_type\\dss_v3_mb_20161207\\dss_v3_mb_prt.dbf'},
        'Nova Scotia': {'shapefile': 'soil_type\\dss_v3_ns_20130715\\dss_v3_ns.shp',
                        'cmp': 'soil_type\\dss_v3_ns_20130715\\dss_v3_ns_cmp.dbf',
                        'soil_layer': 'soil_type\\dss_v3_ns_20130715\\soil_layer_ns_v2.dbf',
                        'prt': 'soil_type\\dss_v3_mb_20161207\\dss_v3_ns_prt.dbf'}
    }
    extend_horizon_depth = 200
    province = 'Manitoba'
    # initialize the scenario first based on the existing default scenario
    particle_density = 2.65
    N1 = 0
    constant_for_oh = 0
    use_default_value = False
    original_scenario_name = 'New Scenario'
    soil_macropore_general_prop = soil_macropore_general_properties(0, 1, 0, 0.5, 0.5)
    soil_infiltration_properties = soil_infiltration_properties(0, 0.4285, 2, 0.99, '1.000E-05', 4000, 2, 0.99, 0,
                                                                '1.000E-09', 0, 10.0, 1000.0, 20.0, 0, '1.0000E-04',
                                                                -15000, -333.0, -15000)
    # # rz data updating flag
    soil_scen_gen = True
    grid_genneral_gen = True
    meteo_gen = True
    soil_gen = True
    station_meta_update = True
    rz_init_update = True

    rzwqm_scenario_mass_generation(stations, original_scenario_path,
                                   shape_file_dict[province]['shapefile'], shape_file_dict[province]['cmp'],
                                   shape_file_dict[province]['soil_layer'], land_cover_map_path, province,
                                   particle_density, N1, constant_for_oh, use_default_value,
                                   original_scenario_name, extend_horizon_depth, soil_macropore_general_prop,
                                   soil_infiltration_properties, 2, soil_scen_gen, meteo_gen, soil_gen,
                                   station_meta_update,
                                   grid_genneral_gen, rz_init_update)
