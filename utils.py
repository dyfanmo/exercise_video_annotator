import cv2
from datetime import datetime, timedelta
import os
import pandas as pd
import requests
import string
import random
import tempfile

from atlas_utils.aws_utils import aws_download_file


def convert_time_to_seconds(time_string):
    date_time = datetime.strptime(time_string, "%H:%M:%S")
    timedelta = date_time - datetime(1900, 1, 1)
    seconds = timedelta.total_seconds()
    return seconds


def convert_time_to_frame_num(time_sting, video_path):
    fps = get_video_fps(video_path)
    seconds = convert_time_to_seconds(time_sting)
    frame_num = int(fps * seconds)
    return frame_num


def convert_frame_num_to_time(frame_number, fps):
    """Converts a frame number to a HH:MM:SS string timestamp"""
    seconds = frame_number / fps
    return str(timedelta(seconds=round(seconds)))


def get_video_fps(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    return fps


def convert_time_to_frame_num_df(df, video_path):
    df["start_frame"] = df["start_time"].apply(lambda time: convert_time_to_frame_num(time, video_path))
    df["end_frame"] = df["end_time"].apply(lambda time: convert_time_to_frame_num(time, video_path))
    return df


def add_labels_column(df):
    unique_exercises = df["exercise"].unique()
    for exercise in unique_exercises:
        exercise_df = df[df["exercise"] == exercise]
        start_time = ""
        id = 0
        for index, exercise_row in exercise_df.iterrows():
            if start_time != exercise_row["start_frame"]:
                start_time = exercise_row["start_frame"]
                id += 1

            df.loc[index, "label"] = exercise + "_" + str(id)

    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
    return df


def get_session(server):
    """Make session send requests with dev token"""
    sess = requests.session()
    username = "vlad@atlasai.co.uk"
    pw = "remote_2020"
    login_endpoint = server + "/auth/login"
    tokens = sess.post(login_endpoint, json={"username": username, "password": pw}).json()
    sess.headers.update({"Authorization": "Bearer " + tokens["access_token"]})
    return sess


def get_random_string(characters=16):
    """Generates a random string"""
    s = "".join(random.choices(string.ascii_uppercase + string.digits, k=characters))
    return s


def checked_value(dict, key, default_value):
    try:
        value = dict[key]
        if value is None or pd.isna(value) or value == "":
            return default_value
        return value
    except KeyError:
        return default_value


def get_server(user_id):
    if user_id > 1000:
        return "https://atlas-remote-prod.atlasaiapi.co.uk/api/v1"
    return "https://atlas-remote-dev.atlasaiapi.co.uk/api/v1"


def send_labels_to_api(user_id, video_result_id, override, labels_df):
    errors = []
    # determine server
    server = get_server(user_id)
    # get token
    session = get_session(server)
    # Check VideoResult exists
    response = session.get(f"{server}/video_result/{video_result_id}")
    if response.status_code != 200:
        return f"Video result with ID {video_result_id} doesn't exist."
    # iterate and post labels
    for (_, label_row) in labels_df.iterrows():
        name = checked_value(label_row, "label", get_random_string())
        request_body = {
            "video_result_id": video_result_id,
            "name": name,
            "exercise": checked_value(label_row, "exercise", ""),
            "view": checked_value(label_row, "orientation", ""),
            "reps": checked_value(label_row, "reps", 0),
            "min_reps": checked_value(label_row, "min_reps", 0),
            "notes": checked_value(label_row, "notes", ""),
            "rules": checked_value(label_row, "rule", ""),
            "reps_to_judge": checked_value(label_row, "reps_to_judge", ""),
            "start_frame": int(checked_value(label_row, "start_frame", 0)),
            "end_frame": int(checked_value(label_row, "end_frame", 0)),
        }

        # send a POST request
        response = session.post(f"{server}/video_label/", json=request_body)
        if response.status_code != 201:
            if override:
                # get video_label_id so we can PUT instead
                response = session.get(
                    f"{server}/video_label/by_name",
                    json={
                        "video_result_id": video_result_id,
                        "name": name,
                    },
                )
                video_label_id = response.json()["id"] if response.status_code == 200 else 0
                response = session.put(f"{server}/video_label/{video_label_id}", json=request_body)
                if response.status_code != 200:
                    errors.append(
                        f"Failed to modify existing label {name} with error: {response.json()['errors']['name']}"
                    )
            else:
                errors.append(f"Failed to create label {name} with error: {response.json()['errors']['name']}")
    # return errors to display to user
    return "\n\n".join(errors)


def download_video_from_s3(user_id, video_result_id):
    """Download video from S3 and put it in tmp dir. Returns filepath to local video"""
    aws_fp = f"{user_id}/{video_result_id}/full_video.ts"
    bucket = "atlas-remote-internal"
    local_fp = os.path.join(tempfile.gettempdir(), "atlas_labelling_full_video.ts")
    aws_download_file(aws_fp, local_fp=local_fp, bucket=bucket)
    return local_fp


def get_labels_from_api(user_id, video_result_id):
    """Get labels for the given video_result_id from the API"""
    server = get_server(user_id)
    session = get_session(server)

    response = session.get(f"{server}/video_label/", json={"video_result_id": video_result_id})
    if response.status_code == 200:
        return response.json()
    return []