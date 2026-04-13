import os
import pandas as pd
import pyproj
from shapely.geometry import Point, shape
import geopandas as gpd
from simpledbf import Dbf5
import rasterio

location_data = {"1016940": [48.62, -123.42], "1096450": [53.89, -122.68], "1100119": [49.24, -121.76],
                 "1108487": [49.25, -123.25], "1127800": [49.57, -119.65], "112G8L1": [49.56, -119.65],
                 "2100630": [60.77, -137.58], "2101200": [60.12, -128.82], "2202110": [61.87, -121.35],
                 "2300500": [64.3, -96.08], "2400800": [70.49, -68.52], "2403500": [74.72, -94.97],
                 "2502700": [76.23, -119.33], "3012295": [53.42, -113.55], "3016761": [53.48, -112.03],
                 "3023720": [52.47, -113.75], "3033890": [49.7, -112.77], "3036652": [51.08, -114.13],
                 "3036681": [50.05, -112.13], "3062244": [53.58, -116.47], "3066001": [55.3, -114.78],
                 "3066920": [55.35, -114.98], "3070560": [55.2, -119.4], "3072720": [58.38, -116.03],
                 "3075040": [56.23, -117.45], "4010879": [50.37, -102.57], "4012400": [49.22, -102.97],
                 "4013490": [50.5, -103.68], "4016640": [50.4, -104.57], "4019035": [51.77, -104.2],
                 "4019080": [51.27, -102.47], "4025047": [50.7, -107.72], "4028040": [50.3, -107.68],
                 "4028060": [50.27, -107.73], "404037Q": [51.32, -108.42], "4043900": [51.52, -109.18],
                 "4043920": [51.47, -109.17], "4055736": [51.48, -107.05], "4057180": [52.15, -106.6],
                 "4061861": [57.35, -107.13], "4064150": [55.15, -105.27], "4075518": [53.33, -104.0],
                 "4083320": [52.87, -102.4], "4083321": [52.82, -102.32], "5021054": [49.65, -97.12],
                 "5021848": [49.18, -98.08], "5023222": [49.92, -97.23], "5023224": [49.92, -97.23],
                 "5031038": [50.63, -97.02], "5043158": [50.71, -99.53], "5052060": [53.72, -101.53],
                 "5062922": [55.8, -97.86], "5062926": [55.75, -97.87], "6016525": [51.45, -90.22],
                 "6020379": [48.75, -91.62], "6073960": [49.4, -82.43], "6104025": [45.0, -75.63],
                 "6105061": [45.3, -75.73], "6105976": [45.38, -75.72], "611KBE0": [44.23, -79.78],
                 "6133360": [42.03, -82.9], "6137730": [42.85, -80.27], "6139145": [43.18, -79.4],
                 "6142285": [43.65, -80.42], "6143083": [43.52, -80.23], "614B2H4": [43.65, -80.42],
                 "6158350": [43.67, -79.4], "6158740": [43.8, -79.55], "7012240": [46.87, -71.65],
                 "7014160": [45.81, -73.43], "7016900": [46.73, -71.5], "7024280": [45.37, -71.82],
                 "7025250": [45.47, -73.75], "7025267": [45.52, -73.57], "7025332": [45.55, -73.17],
                 "7026839": [45.43, -73.93], "7035290": [45.67, -74.03], "7040440": [49.13, -68.2],
                 "7042388": [47.32, -71.15], "7051120": [48.1, -65.68], "7054095": [47.35, -70.03],
                 "7065640": [48.85, -72.53], "7098600": [48.06, -77.79], "7113534": [58.1, -68.42],
                 "7117825": [54.8, -66.82], "8100592": [46.43, -64.77], "8100593": [46.43, -64.77],
                 "8102234": [45.6, -66.57], "8202800": [45.07, -64.48], "8202810": [45.07, -64.48],
                 "8205990": [45.37, -63.27], "8300400": [46.25, -63.13], "8300401": [46.25, -63.13],
                 "8403600": [47.52, -52.78], "8403605": [47.52, -52.78], "8501900": [53.32, -60.42],
                 "8502589": [55.08, -59.18], "8502800": [56.55, -61.68], "8503018": [52.53, -56.3],
                 "8504217": [51.58, -56.72]}

canada_land_cover_properties = {
    '1': 'Temperate or sub-polar needleleaf forest/Forêt de conifères sempervirente tempérée ou subpolaire',
    '2': 'Sub-polar taiga needleleaf forest/ Forêt de conifères (taïga) subpolaire',
    '5': 'Temperate or sub-polar broadleaf deciduous forest/ Forêt feuillue tempérée ou subpolaire',
    '6': 'Mixed forest/ Forêt mixte',
    '8': 'Temperate or sub-polar shrubland/Arbustaie tempérée ou subpolaire',
    '10': 'Temperate or sub-polar grassland/Prairie tempérée ou subpolaire',
    '11': 'Sub-polar or polar shrubland-lichen-moss/Arbustaie à lichens et à mousses polaire ou subpolaire',
    '12': 'Sub-polar or polar grassland-lichen-moss/Prairie à lichens et à mousses polaire ou subpolaire',
    '13': 'Sub-polar or polar barren-lichen-moss/Lande à lichens et à mousses polaire ou subpolaire',
    '14': 'Wetland/Milieu humide',
    '15': 'Cropland/Terre cultivée',
    '16': 'Barren Lands/Lande',
    '17': 'Urban and built-up/Milieu urbain',
    '18': 'Water/Eau',
    '19': 'Snow and Ice/Neige et glace'
}

# Function to detect if the location is cropland
def detect_if_cropland(element):
    if element > 20:
        return 1
    else:
        return 0

def transform_coord(from_crs, to_crs, x, y):
    """Transform coordinates from one CRS to another."""
    transformer = pyproj.Transformer.from_crs(from_crs, to_crs, always_xy=True)
    return transformer.transform(x, y)

def raster_tiff_read_band(raster_path, stations):
    # Open the TIFF file
    returning_dict = {}
    with rasterio.open(raster_path) as dataset:
        for station in stations:
            tiff_crs = dataset.crs
            x, y = transform_coord("EPSG:4326", tiff_crs, stations[station][1], stations[station][0])
            # Convert the geographic coordinate to the pixel coordinate
            row, col = dataset.index(x, y)  # replace lon and lat with your coordinates

            # Read the value at the specified pixel
            value = dataset.read(1)[row, col]
            returning_dict[station] = value
    return returning_dict


def read_dbf_to_dataframe(dbf_file_path):

    dbf = Dbf5(dbf_file_path)
    # for record in dbf:
    #     for key, value in record.items():
    #         if isinstance(value, bytes) and b'y 1' in value:
    #             print(f"Problematic record: {record}")

    # return pd.DataFrame(iter(dbf))
    return dbf.to_dataframe()

def point_in_geom(point, geom):
    return geom.contains(point)


def buffer_point_in_meters(point, distance_in_meters, original_crs):
    """
    Buffer a point by a specified distance in meters, regardless of the original CRS.
    """
    # If the original CRS is geographic (in degrees), convert to UTM for buffering
    if original_crs.is_geographic:
        utm_zone = int((point.x + 186) / 6) + 1  # Simple UTM zone calculation
        utm_crs = f"EPSG:326{utm_zone:02}" if point.y > 0 else f"EPSG:327{utm_zone:02}"
        point_in_utm = point.to_crs(utm_crs)
        buffered = point_in_utm.buffer(distance_in_meters)
        return gpd.GeoSeries([buffered], crs=original_crs)
    else:
        return gpd.GeoSeries(point.buffer(distance_in_meters))


def canada_soil_db_retrieve(soil_db_shapefile_path, cmp_dbf_path, soil_layer_dbf_path, land_cover_map_path, coord_list):
    returning_dict = {}
    failed_stations = []
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)  # You can adjust this value to fit your console width
    pd.set_option("display.max_colwidth", None)

    # Read additional DBF files
    current_directory = os.path.dirname(__file__)
    dbf1_path = os.path.join(current_directory, cmp_dbf_path)
    dbf2_path = os.path.join(current_directory, soil_layer_dbf_path)
    land_cover_map_path = os.path.join(current_directory,land_cover_map_path)

    soil_db_shapefile_path = os.path.join(current_directory, soil_db_shapefile_path)
    df1 = read_dbf_to_dataframe(dbf1_path)
    df2 = read_dbf_to_dataframe(dbf2_path)
    soil_land_cover_dict = raster_tiff_read_band(land_cover_map_path, coord_list)
    shapefile = gpd.read_file(soil_db_shapefile_path)
    soil_attribute_dict = {}
    for key in coord_list:
        # Define the location (longitude, latitude)
        # Create a point object
        point = Point(coord_list[key][1], coord_list[key][0])  # Note: the order is (longitude, latitude)
        point_gdf = gpd.GeoDataFrame({'geometry': [point]}, crs="EPSG:4326")  # Assuming the point is in WGS 84

        # Convert the point to the shapefile's CRS
        point_gdf = point_gdf.to_crs(shapefile.crs)
        selected_id = ''
        soil_attribute = {}
        SOIL_ID = ''
        try:
            selected_feature = shapefile[point_gdf.iloc[0].geometry.within(shapefile.geometry)]
            # select the dominant soil type for the area, if only one soil type, then use the soil type directly
            selected_id = selected_feature['POLY_ID'].iloc[0]
            soil_cmp = df1[df1['POLY_ID'] == selected_id]

            if soil_land_cover_dict[key] == 15:
                # return agriculture disturbed soil profiles
                agricultural_soils = soil_cmp[soil_cmp['PROFILE'] == 'A']
                # return the dominant soil properties
                dominant_soil = agricultural_soils.loc[agricultural_soils['PERCENT'].idxmax()]
            else:
                dominant_soil = soil_cmp.loc[soil_cmp['PERCENT'].idxmax()]
            SOIL_ID = dominant_soil['SOIL_ID']
            soil_attribute['slope'] = dominant_soil['SLOPE_P']
            soil_attribute['stone'] = dominant_soil['STONINESS']
            soil_attribute['slope_len'] = dominant_soil['SLOPE_LEN']

            # return the information for the location
            soil_info = df2[df2['SOIL_ID'] == SOIL_ID].sort_values(by="LAYER_NO")
            # soil_attribute = df3[df3['POLY_ID'] == selected_id]
            ldepth = soil_info['LDEPTH']

            if len(ldepth) == 0:
                failed_stations.append(key)
            elif len(ldepth) > 0:
                returning_dict[key] = soil_info
                soil_attribute_dict[key] = soil_attribute

        except Exception as e:
            print('retry buffering for station {}'.format(key))
            failed_stations.append(key)
        # if selected_id is None or selected_id == '':
        #     buffer_distance = 100
        #     while buffer_distance <= 1000000:
        #         point_gdf = buffer_point_in_meters(point_gdf, buffer_distance, point_gdf.crs)
        #         try:
        #             selected_feature = shapefile[shapefile.geometry.contains(point_gdf.iloc[0])]
        #             #
        #             selected_id = selected_feature['POLY_ID'].iloc[0]
        #             # return the information for the location
        #             SOIL_ID = df1[df1['POLY_ID'] == selected_id].iloc[0]['SOIL_ID']
        #             soil_info = df2[df2['SOIL_ID'] == SOIL_ID].sort_values(by="LAYER_NO")
        #             if selected_id is not None or selected_id != '':
        #                 returning_dict[key] = soil_info
        #                 break
        #         except Exception as e:
        #             buffer_distance = buffer_distance + 100
        #             continue
        #     if selected_id is None or selected_id == '':
        #         failed_stations.append(key)

    return returning_dict, failed_stations, soil_attribute_dict


if __name__ == "__main__":
    # return soil info
    soil_info = canada_soil_db_retrieve('soil_type/dss_v3_mb_20161207/dss_v3_mb.shp',
                                        'soil_type/dss_v3_mb_20161207\\dss_v3_mb_cmp.dbf',
                                        'soil_type/dss_v3_mb_20161207\\soil_layer_mb_v2.dbf',
                                        'soil_type/landcover-2020-classification.tif',
                                        {201: (49.6, -98.70)})
    print(soil_info)

    # testing soil tiff read
    # print(raster_tiff_read('soil_type/landcover-2020-classification.tif',  {201: (49.6, -98.70)}))

    # Process all locations
    # locations = []
    # for loc in location_data.keys():
    #     result = process_location(loc)
    #     if result is not None:
    #         locations.append(result)
