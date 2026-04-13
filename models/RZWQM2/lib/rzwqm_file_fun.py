from datetime import datetime, timedelta

def return_layer_date_count(start,end, month_s, month_e, fmt, start_day):
    #start day is whether the date for the project starts from julien day in the first year
    dates = {}
    s = datetime.strptime(start, fmt)
    e = datetime.strptime(end, fmt)
    length = abs((s-e).days)
    for val in range(length+1):
        #day = s + timedelta(days=val+1)
        #from the range between the two dates, start with the start date, store to the list
        day = s + timedelta(days=val)
        if day.month >= month_s or day.month <=month_e:
            c = val + start_day
            dates[c] = day
    return dates

def return_dates_within_range(start, end, fmt):
    sdate = datetime.strptime(start, fmt)  # start date
    edate = datetime.strptime(end, fmt)  # end date
    date_modified = sdate
    return_list = [sdate]

    while date_modified < edate:
        date_modified += timedelta(days=1)
        return_list.append(date_modified)

    return return_list