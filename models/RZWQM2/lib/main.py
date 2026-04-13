from geopy.geocoders import Nominatim

locator = Nominatim(user_agent='myGeocoder')

lines = []
lines_parsed = []
# open the data file, and import them into a list
with open('snow_data.txt', encoding="utf8") as file:
    lines = [line.rstrip('\n') for line in file]

# parsing the list
for line in lines:
    split = line.split()
    lines_parsed.append(split)
# location list stores the reversed lan and lon
location_reversed_list = []
# station data contains all the information for each station
station_data = []
# stores the info for the corresponding lan and lon to address
lanlon_to_place = []

for item in lines_parsed:
    # find the location based on the lan and lon
    lan = item[1]
    lon = item[2]
    cord = f"{lan}, {lon}"
    location_final = ''

    # see if this location has been discovered, if not, then create a new obj
    if cord not in location_reversed_list:
        location_reversed_list.append(cord)
        location = locator.reverse(f"{lan}, {lon}")
        # add the reversed coordination to the list
        location_reversed_list.append(location)
        # store the searched data
        lanlon_to_place.append({"location": location[0], "lanlon": cord})
        # create the object for this station
        obj = {"location": location[0], "data": []}
        station_data.append(obj)
        location_final = obj["location"]
    else:
        for x in lanlon_to_place:
            if x['lanlon'] == cord:
                location_final = x['location']

    for val in station_data:
        if val["location"] == location_final:
            val["data"].append(item)

for station in station_data:
    with open('parsed_data.txt', 'a') as f:
        f.write("%s\n" % station["location"])
    with open('parsed_data.txt', 'a') as f:
        for item in station["data"]:
            f.write("%s\n" % item)
