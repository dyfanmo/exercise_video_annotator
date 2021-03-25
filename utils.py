import cv2
from datetime import datetime


def convert_time_to_seconds(time_string):
    date_time = datetime.strptime(time_string, "%H:%M:%S")
    timedelta = date_time - datetime(1900, 1, 1)
    seconds = timedelta.total_seconds()
    return seconds


def convert_time_to_frame_num(time_sting, video_path):
    fps = get_video_fps(video_path)
    seconds = convert_time_to_seconds(time_sting)
    frame_num = fps * seconds
    return frame_num


def get_video_fps(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    return int(fps)


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


def send_labels_to_api(user_id, video_result_id, override, labels_df):
    # determine server
    # get token
    # iterate and post labels
    # if override, put failing posts
    # return errors to display to user
    pass
