import wget
import requests

link = 'https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID={}&Year={}&Month={}&Day=14&timeframe={}&submit=Download+Data'
path_to_dl_folder = '../data'


class DL_eccc:
    def __init__(self):
        self.syntax = link

    def download_data(self, stationID, year, path, month=1, time=2):
        f_link = self.syntax.format(stationID, year, month, time)
        file_name = wget.download(f_link, out=path)
        return file_name


if __name__ == '__main__':
    dl = DL_eccc()
    dl.download_data('6139525', 2005, path_to_dl_folder)
