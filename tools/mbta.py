import numpy as np
import pandas as pd
import requests
import json
import time
from copy import deepcopy

def _get_stop_name(id):
    try:
        stp = requests.get('https://api-v3.mbta.com/stops/%s' % str(id))
        stop_dict = json.loads(stp.text)['data']['attributes']
        return stop_dict
    except:
        return {'name': None}
    
def _get_stop_name(id):
    try:
        stp = requests.get('https://api-v3.mbta.com/stops/%s' % str(id))
        stop_dict = json.loads(stp.text)['data']['attributes']
        return stop_dict
    except:
        return {'name': None}
    
def _normalize_and_drop(df, cols):
    if not type(cols) == list:
        cols = [cols]
    for c in cols:
        c_exp = pd.json_normalize(df[c])
        df.drop(columns=c, inplace=True)
        df = pd.concat([df, c_exp], axis=1)
    return df

'''stop_df = Stops()

r = requests.get('https://api-v3.mbta.com/alerts?page%5Boffset%5D=0&page%5Blimit%5D=100&sort=active_period&fields%5Balert%5D=header&include=routes%2Cstops&filter%5Bactivity%5D=BOARD%2CEXIT%2CRIDE')
r = json.loads(r.text)'''

def _time_to_now(schedule):
    try:
        parsed_times = [time.strptime(s.arrival_time[:-6], '%Y-%m-%dT%H:%M:%S') for s in schedule.iloc]
        parsed_times = [int((time.mktime(a) - time.time())/60) for a in parsed_times]
        schedule['wait'] = parsed_times
    except:
        schedule['wait'] = [[] for _ in schedule.iloc]
    return schedule

def schedule_by_stop_id(x, current_time=None):
    if current_time is None:
        h = time.strftime('%H', time.localtime())
        m = time.strftime('%M', time.localtime())
    else:
        h, m = current_time.split(':')
    link = 'https://api-v3.mbta.com/schedules?filter%5Bmin_time%5D={}%3A{}&filter%5Bstop%5D={}'.format(h, m, x)
    schedule = requests.get(link)
    schedule = pd.DataFrame.from_dict(json.loads(schedule.text)['data'])
    schedule = _normalize_and_drop(schedule, ['attributes', 'relationships'])
    schedule = _time_to_now(schedule)
    return schedule

class Stops:
    def __init__(self):
        self._refresh()

    def _refresh(self):
        stops = requests.get('https://api-v3.mbta.com/stops')
        stop_info = pd.DataFrame.from_dict(json.loads(stops.text)['data'])
        stop_info = _normalize_and_drop(stop_info, ['attributes', 'links', 'relationships'])
        stop_info.set_index('id', inplace=True)
        stop_info.fillna(-1, inplace=True)
        stop_info.vehicle_type = stop_info.vehicle_type.astype(int)
        self.info = stop_info

    def lookup(self, name='', vehicle='rapid', desc='', full=False):
        df = self.info[self.info.name.str.contains(name)]
        df = self._filter_vehicle(df, vehicle)
        try:
            df = df[df.description.str.contains(desc, na=False)]
        except:
            if desc != '': print('No descriptions matching', desc)
        return df
    
    def localize(self, coords, vehicle='rapid', dist=1, full=False):
        df = deepcopy(self.info)
        df = self._filter_vehicle(df, vehicle)
        # Latitude: 1 degree = 68.72219 mi
        # Longitude: 1 degree = 69.18583 mi * cos(Latitude deg)
        lat, lon = coords
        statlat, statlon = df.latitude, df.longitude
        distlat = np.array([(sl - lat) * 68.72219 for sl in statlat.iloc])
        distlon = np.array([(sl - lon) * (69.18583 * np.cos(lat * np.pi / 180)) for sl in statlon.iloc])
        df['dist'] = np.sqrt(distlat**2 + distlon**2)
        if full:
            return df[df.dist < dist]
        else:
            return _clean_view(df[df.dist < dist])
        
    def _filter_vehicle(self, df, vehicle):
        if vehicle=='rapid': df = df[df.vehicle_type.between(0,1)]
        elif vehicle=='commuter': df = df[df.vehicle_type==2]
        elif vehicle=='bus': df = df[df.vehicle_type==3]
        return df
    
class Routes:
    def __init__(self):
        self._refresh()

    def _refresh(self):
        routes = requests.get('https://api-v3.mbta.com/routes')
        route_info = pd.DataFrame.from_dict(json.loads(routes.text)['data'])
        stop_info = _normalize_and_drop(stop_info, ['attributes', 'links', 'relationships'])
        stop_info.set_index('id', inplace=True)
        stop_info.fillna(-1, inplace=True)
        stop_info.vehicle_type = stop_info.vehicle_type.astype(int)
        self.info = stop_info

class Schedules:
    def __init__(self):
        pass
    
def _clean_view(df):
    if 'dist' in df.columns:
        return df[['name', 'description', 'dist']]
    else:
        return df[['name', 'description']]
    
def lookup_route_for_stops(id):
    pass
        
def schedule_for_stops(stops_df, next_min=30):
    stops_df['waits'] = [schedule_by_stop_id(i)['wait'].sort_values() for i in stops_df.index]
    stops_df['waits'] = [np.array(a)[a<next_min] for a in stops_df['waits']]
    return stops_df