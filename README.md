# Python Annotator for VideoS

## Installation
 * Windows
  ```
     pip install numpy
     pip install PyQt5
     Run [Required software for Windows/K-Lite_Codec_Pack_1532_Basic.exe]https://github.com/dyfanmo/exercise_video_annotator/blob/main/Required%20software%20for%20Windows/K-Lite_Codec_Pack_1532_Basic.exe file to support video

```

 * Linux/Ubuntu
  ```
     pip install numpy
     sudo apt-get install python3-pyqt5
```

## Usage
   * Running the annotator
 ```
     python pavs.py --classes_label_path config/classes.txt 

```

## Shortcuts
- Load video: L
- Previous frame: Left Arrow
- Next frame: Right Arrow
- Add Start Time: [
- Add End Time: ]
- Frame after next 10 frames: Shift + Left Arrow
- Frame before prev 10 frames: Shift + Right Arrow
- Clear entire table: C
