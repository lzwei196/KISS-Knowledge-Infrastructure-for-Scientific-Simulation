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

    def find_date(self):
        if self.s == 'Date/Time':
            return True
        elif self.s == 'Date (Local Standard Time)':
            return True
        elif self.s == 'Date/Time (LST)':
            return True
        elif self.s == '# Date':
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
        elif self.s == 'Snow on Grnd (cm)':
            return True