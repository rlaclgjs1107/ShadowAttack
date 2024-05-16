import json
import os
import sys
from pathlib import Path
from typing import List, Union

import cv2
from cv2.typing import MatLike
from pydantic import BaseModel
from settings import VIDEO_DIR


class Position(BaseModel):
    x: float
    y: float
    width: float
    height: float
    frame: int


class Object(BaseModel):
    object_id: str
    label: Union[str, List[str]]
    sequence: List[Position]


def interpolate_position(pos1: Position, pos2: Position, frame: int) -> Position:
    if pos1.frame == pos2.frame:
        return pos1
    ratio = (frame - pos1.frame) / (pos2.frame - pos1.frame)
    x = pos1.x + (pos2.x - pos1.x) * ratio
    y = pos1.y + (pos2.y - pos1.y) * ratio
    width = pos1.width + (pos2.width - pos1.width) * ratio
    height = pos1.height + (pos2.height - pos1.height) * ratio
    return Position(x=x, y=y, width=width, height=height, frame=frame)


def update_sequence_with_interpolation(sequence: List[Position], frame_count: int) -> List[Position]:
    new_sequence: List[Position] = []
    for i in range(frame_count):
        for j in range(len(sequence) - 1):
            if sequence[j].frame <= i < sequence[j + 1].frame:
                new_pos = interpolate_position(sequence[j], sequence[j + 1], i)
                new_sequence.append(new_pos)
                break
    return new_sequence


def load_objects(json_file: str) -> List[Object]:
    with open(json_file, "rb") as f:
        data = json.load(f)[0]
    result = data["annotations"][0]["result"]
    objects: List[Object] = []
    for res in result:
        object_id = res["id"]
        if "labels" in res["value"]:
            label = res["value"]["labels"]
        else:
            label = "blank"
        sequence = res["value"]["sequence"]
        positions = [Position(**pos) for pos in sequence]
        obj = Object(object_id=object_id, label=label, sequence=positions)
        objects.append(obj)
    return objects


def crop_and_save_frame(frame: MatLike, pos: Position, output_dir: str):
    original_height, original_width = frame.shape[:2]
    pixel_x = pos.x / 100.0 * original_width
    pixel_y = pos.y / 100.0 * original_height
    pixel_width = pos.width / 100.0 * original_width
    pixel_height = pos.height / 100.0 * original_height
    cropped_frame = frame[int(pixel_y):int(pixel_y + pixel_height), int(pixel_x):int(pixel_x + pixel_width)]
    output_file = os.path.join(output_dir, f"{pos.frame}.jpg")
    cv2.imwrite(output_file, cropped_frame)


def error(msg: str, exit_code: int = -1):
    print(f"Error: {msg}")
    sys.exit(exit_code)


def main(file_path: Path):
    video_base_name = os.path.basename(file_path).split(".")[0]
    # This json file is exported from Label Studio (To make this json file, we need some manual work, labeling key frames)
    objects = load_objects(str(VIDEO_DIR / f"{video_base_name}.json")) 

    output_base_path = str(VIDEO_DIR / f"{video_base_name}-frames") + "/"
    if not os.path.exists(output_base_path):
        os.makedirs(output_base_path)
    
    for obj in objects:
        if not os.path.exists(output_base_path + obj.object_id):
            os.makedirs(output_base_path + obj.object_id)

    for obj in objects:
        frame_count = obj.sequence[-1].frame + 1
        obj.sequence = update_sequence_with_interpolation(obj.sequence, frame_count)

    cap = cv2.VideoCapture(str(file_path))
    print(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        for obj in objects:
            for pos in obj.sequence:
                if pos.frame == frame_idx:
                    crop_and_save_frame(frame, pos, output_base_path + obj.object_id)
        frame_idx += 1



if __name__ == "__main__":
    if len(sys.argv) != 2:
        error("Usage: python video_preprocess.py <video_file in videos/>")

    video_file_name = sys.argv[1]
    video_file_path = VIDEO_DIR / video_file_name

    if not os.path.exists(video_file_path):
        error("File does not exist")

    if not video_file_name.endswith(".mp4"):
        error("Please provide a .mp4 file")

    main(video_file_path)
