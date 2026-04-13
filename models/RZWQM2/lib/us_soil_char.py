import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def get_feature_id_from_coord(gdb_path, layer_name, point):
    # Load the GDB layer into a GeoDataFrame
    point = Point(point)

    gdf = gpd.read_file(gdb_path, layer=layer_name)

    df = pd.DataFrame({'geometry': [point]})

    # Convert DataFrame to GeoDataFrame
    gdf_point = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")

    # Assign CRS to GeoDataFrame
    gdf_point = gdf_point.to_crs("EPSG:5070")


    # Loop through the GeoDataFrame to find the feature containing the point
    for idx, row in gdf.iterrows():
        # print(row['geometry'])
        if row['geometry'].contains(gdf_point.iloc[0].geometry):
            return row['MUKEY']  # Assuming the feature ID is stored in a column named 'FeatureID'



    return None  # Return None if no feature contains the point


# Example usage:
gdb_path = "./us_soil_db_layer/gSSURGO_GA.gdb"
layer_name = "MUPOLYGON"
x, y = -85.35460,34.74607 # Replace with your coordinates

feature_id = get_feature_id_from_coord(gdb_path, layer_name, [(x, y)])
if feature_id is not None:
    print(f"Feature ID: {feature_id}")
else:
    print("Point not contained in any feature.")
