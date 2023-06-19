import logging
from pathlib import Path
from typing import Union, List

import numpy as np
import pandas as pd

from stonexgps.utils.gnss_crd import llh2xyz
from stonexgps.utils.gnss_time import ymdhms2wksow


def strtime2gpstime(ymd: str, hms: str) -> List[float]:
    year = int(ymd[0:4])
    month = int(ymd[5:7])
    day = int(ymd[8:10])
    hour = int(hms[0:2])
    minite = int(hms[3:5])
    second = float(hms[6:])
    week, sow = ymdhms2wksow(year, month, day, hour, minite, second)
    return [week, sow]

def read_RTKLIB_pos(fname: Union[str, Path]):
    """
    read_RTKLIB_pos _summary_
    function inspired by https://github.com/lzhuance/PPP_AR-master-vscode/blob/7a09e0ede76630c9ccf881f2fd56600b4ca79e28/py_analysis/read_pos.py

    Args:
        fname (Union[str, Path]): _description_

    Returns:
        _type_: _description_
    """

    traj_file = Path(fname)
    assert traj_file.exists(), "Trajectory file does not exist."
    assert traj_file.suffix == ".pos", "Trajectory file is not a .pos file."    

    f = open(traj_file)
    ln = f.readline()
    
    # Read the header
    while ln:
        ln = f.readline()
        if ln[0] == '%':
            ele = ln.split()
            if "obs start" in ln:
                obs_start = ele[4]+" "+ele[5]
                time_fmt = ele[6]
                gps_week, gps_sow = ele[7].replace("(week", ""), ele[8].replace(")", "")
                continue
            elif "obs end" in ln:
                obs_end = ele[4]+" "+ele[5]
                continue
            elif "ref pos" in ln:
                ref_pos = [float(x) for x in ele[4:7]]
                continue
            elif "latitude(deg)" in ln:
                type = 'LLH'
                break
            elif "x-ecef(m)" in ln:
                type = 'XYZ'
                logging.error("Not support XYZ trajectory file yet")
                return None
    ln = f.readline()
    
    metadata = {"obs_start": obs_start, "obs_end": obs_end, "ref_pos": ref_pos, "coord_type": type, "time_fmt": time_fmt, "gps_week": gps_week, "gps_sow": gps_sow}

    # Read the data
    ep = 0
    data = {}
    while ln:
        if ln[0] != '%' and ln[0] != '\n':
            ele = ln.split()
            ymd = ele[0]
            hms = ele[1]
            time = strtime2gpstime(ymd, hms)
            if type == 'XYZ':
                logging.error("Not support XYZ trajectory file yet")
                return None                 
            elif type == 'LLH':
                llh = [float(x) for x in ele[2:5]]
                xyz = llh2xyz(np.array(llh)).tolist()
            else:
                return None

            Q, ns = [int(x) for x in ele[5:7]]
            stdev = [float(x) for x in ele[7:13]]
            age, ratio = [float(x) for x in ele[13:15]]

            data[ep] = [ymd, hms, *time, *llh, *xyz, Q, ns, *stdev, age, ratio]

            ep += 1
        ln = f.readline()

    f.close()
    logging.info("RTKLIB pos file successfully read.")

    # Convert to pandas dataframe
    df = pd.DataFrame.from_dict(data, orient='index', columns=['ymd', 'hms', 'week', 'sow', 'lat', 'lon', 'h_ell', 'x', 'y', 'z', 'Q', 'ns', 'sdn', 'sde', 'sdu', 'sdne', 'sdeu', 'sdun', 'age', 'ratio'])

    df[f"datetime_{metadata['time_fmt']}"] = pd.to_datetime(df["ymd"]+"_"+df["hms"], format="%Y/%m/%d_%H:%M:%S.%f")

    # Convert to UTC time by subtracting Leap Second (18 seconds)
    if metadata["time_fmt"].lower() == "gpst":
        df["datetime_UTC"] = pd.to_datetime(df["ymd"]+"_"+df["hms"], format="%Y/%m/%d_%H:%M:%S.%f", utc=True) - pd.to_timedelta(18, unit='s')

    # Convert to Rome time
    dti = pd.DatetimeIndex(df["datetime_UTC"])
    df["datetime_ROME"] = dti.tz_convert('Europe/Rome')

    logging.info("Trajectory converted to pandas dataframe.")

    return df, metadata

def read_stonex_link_file(fname: Union[str, Path], sep: str = ";") -> pd.DataFrame:
    fname = Path(fname)
    assert fname.exists(), "Trajectory file does not exist."    

    with open(fname) as f:
        lines = f.readlines()
    
    data = {}
    for i, line in enumerate(lines):  
        ln = line.split(sep)
        name = ln[2]
        ant = ln[9]
        start = ln[-3]
        end = ln[-2]
        data[i] = [name, ant, start, end]

    # Specify column names
    # TODO: read the rest of the columns from the file
    column_names = ["point", "h_ant","start", "end"]

    # Convert to pandas dataframe
    df = pd.DataFrame.from_dict(data, orient='index', columns=column_names)
    for col in ["start", "end"]:
        df[f"{col}_UTC"] = pd.to_datetime(df[col], format="%Y/%m/%d %H:%M:%S.%f", utc=True) - pd.to_timedelta(18, unit='s')
        dti = pd.DatetimeIndex(df[f"{col}_UTC"])
        df[f"{col}_ROME"] = dti.tz_convert('Europe/Rome')

    return df


def extract_point_from_trajectory(trajectory: pd.DataFrame, points: pd.DataFrame, only_fixed: bool = True) -> pd.DataFrame:

    out = {}
    for i, point in enumerate(stonex["point"]):
        point = points["point"][i]
        start = points["start_UTC"][i]
        end = points["end_UTC"][i]

        track = trajectory[(trajectory["datetime_UTC"] >= start) & (trajectory["datetime_UTC"] <= end)]

        if only_fixed:
            num_obs = len(track)
            track = track[track["Q"] == 1]
            logging.info(f"Only fixed solution selected. {len(track)} out of {num_obs} observations are fixed.")

        if len(track) == 0:
            logging.error("No data found for point %s", point)
            raise ValueError("No data found for point %s", point)

        avg = track.mean(axis=0, skipna=True, numeric_only=True)
        std = track.std(axis=0, skipna=True, numeric_only=True)


        out[i] = [point, avg["lat"], avg["lon"], avg["h_ell"], std["lat"], std["lon"], std["h_ell"], start, end, len(track)]

    column_names = ["point", "lat", "lon", "h_ell", "lat_std", "lon_std", "h_ell_std", "start", "end", "num_obs"]
    out_df = pd.DataFrame.from_dict(out, orient='index', columns=column_names)

    return out_df


if __name__ == "__main__":
    
    traj_file = "data/1_2023-06-17-06-40-38.pos"
    stonex_file = "data/rover_cubelink.txt"

    traj, metadata = read_RTKLIB_pos(traj_file)
    stonex = read_stonex_link_file(stonex_file)

    averaged = extract_point_from_trajectory(traj, stonex, only_fixed=True)
    averaged.to_csv("data/averaged.csv", index=False)

    print("Done.")


   