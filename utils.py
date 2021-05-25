import cv2
from datetime import datetime, timedelta
import os
import pandas as pd
import requests
import string
import random
import tempfile

from atlas_utils.aws_utils import aws_download_file, aws_upload_file
from atlas_utils.vid_utils import get_video_fps
from atlas_utils.evaluation_framework.report_generation.form_error.calculate_form_error import form_threshold_dict


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


def delete_existing_labels(server, session, video_result_id):
    response = session.get(f"{server}/video_label/", json={"video_result_id": video_result_id})

    for label in response.json():
        session.delete(f"{server}/video_label/{label['id']}")


def send_labels_to_api(user_id, video_result_id, labels_df):
    errors = []

    server = get_server(user_id)
    session = get_session(server)

    # Check VideoResult exists
    response = session.get(f"{server}/video_result/{video_result_id}")
    if response.status_code != 200:
        return f"Video result with ID {video_result_id} doesn't exist."

    delete_existing_labels(server, session, video_result_id)

    # iterate and post labels
    for (_, label_row) in labels_df.iterrows():
        name = checked_value(label_row, "label", get_random_string())
        request_body = {
            "video_result_id": video_result_id,
            "name": name,
            "exercise": checked_value(label_row, "exercise", ""),
            "view": checked_value(label_row, "orientation", ""),
            "reps": int(checked_value(label_row, "reps", 0)),
            "min_reps": int(checked_value(label_row, "min_reps", 0)),
            "notes": checked_value(label_row, "notes", ""),
            "rules": checked_value(label_row, "rule", ""),
            "reps_to_judge": checked_value(label_row, "reps_to_judge", ""),
            "start_frame": int(checked_value(label_row, "start_frame", 0)),
            "end_frame": int(checked_value(label_row, "end_frame", 0)),
            "is_valid": str(checked_value(label_row, "is_valid", "")),
        }

        # send a POST request
        response = session.post(f"{server}/video_label/", json=request_body)
        if response.status_code != 201:
            # get video_label_id so we can PUT instead
            response = session.get(
                f"{server}/video_label/by_name",
                json={
                    "video_result_id": video_result_id,
                    "name": name,
                },
            )
            if response.status_code == 200:
                video_label_id = response.json()["id"]
                response = session.put(f"{server}/video_label/{video_label_id}", json=request_body)
                if response.status_code != 200:
                    errors.append(
                        f"Failed to modify existing label {name} with error: {response.json()['errors']['name']}"
                    )
            else:
                errors.append(f"Failed to find label with name '{name}'")
    # return errors to display to user
    return "\n\n".join(errors)


def download_file_from_s3(user_id, video_result_id, filename, local_fp=""):
    """Download file from S3 and put it in tmp dir. Returns filepath to local file"""
    aws_fp = f"{user_id}/{video_result_id}/{filename}"
    bucket = "atlas-remote-internal"
    if local_fp == "":
        local_fp = os.path.join(tempfile.gettempdir(), filename)
    aws_download_file(aws_fp, local_fp=local_fp, bucket=bucket)
    return local_fp


def upload_file_to_s3(user_id, video_result_id, filename):
    """Upload file to S3"""
    object_name = f"{user_id}/{video_result_id}/{os.path.basename(filename)}"
    bucket = "atlas-remote-internal"
    aws_upload_file(filename, bucket=bucket, object_name=object_name)


def get_labels_from_api(user_id, video_result_id):
    """Get labels for the given video_result_id from the API"""
    server = get_server(user_id)
    session = get_session(server)

    response = session.get(f"{server}/video_label/", json={"video_result_id": video_result_id})
    if response.status_code == 200:
        return response.json()
    return []


def add_is_valid_column_values(label_df):
    for idx, label_row in label_df.iterrows():
        is_valid = (
            label_row["is_valid"] is not False
            and label_row["exercise"] in form_threshold_dict
            and label_row["orientation"] in form_threshold_dict[label_row["exercise"]]
        )
        label_df.loc[idx, "is_valid"] = is_valid

    return label_df


def get_video_filename_from_api(user_id, video_result_id):
    """Get filename of video from the results bucket"""
    default = "full_video.ts"
    server = get_server(user_id)
    session = get_session(server)
    response = session.get(f"{server}/video_result/{video_result_id}")
    if response.status_code != 200:
        return default

    full_path = response.json()["internal_s3_raw_video_path"]
    if full_path == "" or full_path is None:
        return default
    try:
        i = full_path.rindex("/")
        return full_path[i + 1 :]
    except:
        return full_path
