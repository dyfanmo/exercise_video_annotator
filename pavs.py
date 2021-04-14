from PyQt5.QtWidgets import (
    QMainWindow,
    QApplication,
    QPushButton,
    QLineEdit,
    QComboBox,
    QFileDialog,
    QStyleFactory,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
    QStatusBar,
    QTableWidget,
    QVBoxLayout,
    QTableWidgetItem,
    QHBoxLayout,
    QSplitter,
    QGroupBox,
    QFormLayout,
    QAction,
    QGridLayout,
    QShortcut,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
)
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5 import QtCore, Qt, QtGui
from PyQt5.QtCore import QRect, QSize, Qt, QUrl, QDir, QTime, pyqtSlot
from PyQt5.QtGui import QFont, QPixmap, QImage, QColor, QPainter, QPen, QKeySequence, QStandardItemModel, QIntValidator
import os
import csv
import sys
import numpy as np
import argparse
import pandas as pd
import tempfile
import subprocess
import shutil
import traceback
from utils import (
    convert_time_to_frame_num_df,
    add_labels_column,
    send_labels_to_api,
    download_file_from_s3,
    get_labels_from_api,
    get_video_fps,
    convert_frame_num_to_time,
    upload_file_to_s3,
)

from atlas_utils.evaluation_framework.generate_report import generate_report
from atlas_utils.vid_utils import vid_to_frames


parser = argparse.ArgumentParser()
parser.add_argument("--classes_label_path", type=str, default="config/classes.txt")
parser.add_argument("--rules_path", type=str, default="config/rules.txt")
args = parser.parse_args()

audio_extensions = [".wav", ".mp3"]
video_extensions = [".avi", ".mp4", ".mkv"]


def showErrorDialog(message):
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)

    msg.setWindowTitle("Error")
    msg.setText("There are errors, see details.")
    msg.setDetailedText(message)
    msg.setStandardButtons(QMessageBox.Ok)

    msg.exec_()


def showDialog(message, success=True):
    msg = QMessageBox()
    msg.setStandardButtons(QMessageBox.Ok)

    title = "Success"
    icon = QMessageBox.Information
    text = message

    if not success:
        title = "Error"
        icon = QMessageBox.Critical
        text = "There are errors, see details."
        msg.setDetailedText(message)

    msg.setWindowTitle(title)
    msg.setIcon(icon)
    msg.setText(text)

    msg.exec_()


class ExportDBInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.userId = QLineEdit(self)
        self.videoResultId = QLineEdit(self)
        buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)

        self.override = False
        self.onlyInt = QIntValidator()
        self.userId.setValidator(self.onlyInt)
        self.videoResultId.setValidator(self.onlyInt)

        layout = QFormLayout(self)
        layout.addRow("User ID", self.userId)
        layout.addRow("Video Result ID", self.videoResultId)
        layout.addWidget(buttonBox)

        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

    def getInputs(self):
        return (self.userId.text(), self.videoResultId.text())


class OpenVideoInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.userId = QLineEdit(self)
        self.videoResultId = QLineEdit(self)
        self.videoFilepath = ""
        buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        openButton = QPushButton("Choose...")
        openButton.clicked.connect(self.openFile)

        self.onlyInt = QIntValidator()
        self.userId.setValidator(self.onlyInt)
        self.videoResultId.setValidator(self.onlyInt)

        layout = QFormLayout(self)
        layout.addRow(QLabel("From S3 bucket"))
        layout.addRow("User ID", self.userId)
        layout.addRow("Video Result ID", self.videoResultId)
        layout.addWidget(buttonBox)
        layout.addRow(QLabel("From local files"))
        layout.addWidget(openButton)

        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

    def getInputs(self):
        return (self.userId.text(), self.videoResultId.text(), self.videoFilepath)

    def openFile(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "Open Movie", QDir.homePath())
        self.videoFilepath = fileName
        self.accept()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()

        self.title = "Exercise Video Annotator"
        self.InitWindow()

    def InitWindow(self):
        self.setWindowTitle(self.title)
        self.setWindowState(QtCore.Qt.WindowMaximized)

        self.UiComponents()

        self.show()

    def UiComponents(self):

        self.rowNo = 1
        self.colNo = 0
        self.fName = ""
        self.fName2 = ""
        self.video_file_path = ""
        self.dropDownName = ""
        self.userId = -1
        self.videoResultId = -1
        self.tmpDir = os.path.join(tempfile.gettempdir(), "atlas_labelling_tool")

        self.model = QStandardItemModel()

        self.mediaPlayer = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.tableWidget = QTableWidget()
        self.tableWidget.cellClicked.connect(self.checkTableFrame)

        self.videoWidget = QVideoWidget()
        self.frameID = 0

        self.insertBaseRow()

        openButton = QPushButton("Open...")
        openButton.clicked.connect(self.openFile)

        self.playButton = QPushButton()
        self.playButton.setEnabled(False)
        self.playButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.playButton.clicked.connect(self.play)

        self.lbl = QLabel("00:00:00")
        self.lbl.setFixedWidth(60)
        self.lbl.setUpdatesEnabled(True)

        self.elbl = QLabel("00:00:00")
        self.elbl.setFixedWidth(60)
        self.elbl.setUpdatesEnabled(True)

        self.playbackIndicator = QLabel("X" + str(self.mediaPlayer.playbackRate()))
        self.playbackIndicator.setFixedWidth(60)
        self.playbackIndicator.setUpdatesEnabled(True)

        self.nextButton = QPushButton("-->")
        self.nextButton.clicked.connect(self.next)

        self.delButton = QPushButton("Delete")
        self.delButton.clicked.connect(self.delete)

        self.exportToCsvButton = QPushButton("Export to CSV")
        self.exportToCsvButton.clicked.connect(self.exportCsv)

        self.exportToDbButton = QPushButton("Export to DB")
        self.exportToDbButton.clicked.connect(self.exportDb)

        self.importButton = QPushButton("Import")
        self.importButton.clicked.connect(self.importCSV)

        self.reportButton = QPushButton("Generate report")
        self.reportButton.clicked.connect(self.generateReport)

        self.startTime = QLineEdit()
        self.startTime.setPlaceholderText("Start Time")

        self.endTime = QLineEdit()
        self.endTime.setPlaceholderText("End Time")

        self.minReps = QLineEdit()
        self.minReps.setPlaceholderText("Min Reps")

        self.maxReps = QLineEdit()
        self.maxReps.setPlaceholderText("Reps")

        self.repsToJudge = QLineEdit()
        self.repsToJudge.setPlaceholderText("Reps To Judge")

        self.iLabel = QComboBox(self)
        exercise_file = open(args.classes_label_path, "r")
        exercise_list = [line.split(",") for line in exercise_file.readlines()]
        for exercise_class in exercise_list:
            self.iLabel.addItem(exercise_class[0].strip())
        self.iLabel.activated[str].connect(self.style_choice)

        self.rules = QComboBox(self)
        rules_file = open(args.rules_path, "r")
        rules_list = [line.split(",") for line in rules_file.readlines()]
        for rule in rules_list:
            self.rules.addItem(rule[0].strip())
        self.rules.activated[str].connect(self.style_choice)

        self.orientation = QComboBox(self)
        self.orientation.addItem("front")
        self.orientation.addItem("side")
        self.orientation.addItem("diagonal")
        self.orientation.activated[str].connect(self.style_choice)

        self.positionSlider = QSlider(Qt.Horizontal)
        self.positionSlider.setRange(0, 100)
        self.positionSlider.sliderMoved.connect(self.setPosition)
        self.positionSlider.sliderMoved.connect(self.handleLabel)
        self.positionSlider.setSingleStep(2)
        self.positionSlider.setPageStep(20)
        self.positionSlider.setAttribute(Qt.WA_TranslucentBackground, True)

        self.errorLabel = QLabel()
        self.errorLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # Main plotBox
        plotBox = QHBoxLayout()

        controlLayout = QHBoxLayout()
        controlLayout.addWidget(openButton)
        controlLayout.addWidget(self.playButton)
        controlLayout.addWidget(self.lbl)
        controlLayout.addWidget(self.positionSlider)
        controlLayout.addWidget(self.elbl)
        controlLayout.addWidget(self.playbackIndicator)

        wid = QWidget(self)
        self.setCentralWidget(wid)

        # Left Layout{
        layout = QVBoxLayout()
        layout.addWidget(self.videoWidget, 1)
        layout.addLayout(controlLayout)
        layout.addWidget(self.errorLabel)

        plotBox.addLayout(layout, 1)
        # }

        # Right Layout {
        inputFields = QHBoxLayout()
        inputFields.addWidget(self.startTime, 1)
        inputFields.addWidget(self.endTime, 1)
        inputFields.addWidget(self.iLabel, 1)
        inputFields.addWidget(self.orientation, 1)
        inputFields.addWidget(self.minReps, 1)
        inputFields.addWidget(self.maxReps, 1)
        inputFields.addWidget(self.rules, 1)
        inputFields.addWidget(self.repsToJudge, 1)

        feats = QHBoxLayout()
        feats.addWidget(self.nextButton)
        feats.addWidget(self.delButton)
        feats.addWidget(self.exportToCsvButton)
        feats.addWidget(self.exportToDbButton)
        feats.addWidget(self.importButton)
        feats.addWidget(self.reportButton)

        layout2 = QVBoxLayout()
        layout2.addWidget(self.tableWidget)
        layout2.addLayout(inputFields, 1)
        layout2.addLayout(feats, 2)
        # }

        plotBox.addLayout(layout2, 2)

        wid.setLayout(plotBox)

        self.shortcut = QShortcut(QKeySequence("["), self)
        self.shortcut.activated.connect(self.addStartTime)
        self.shortcut = QShortcut(QKeySequence("]"), self)
        self.shortcut.activated.connect(self.addEndTime)
        self.shortcut = QShortcut(QKeySequence("L"), self)
        self.shortcut.activated.connect(self.openFile)
        self.shortcut = QShortcut(QKeySequence("C"), self)
        self.shortcut.activated.connect(self.copyRow)
        self.shortcut = QShortcut(QKeySequence("R"), self)
        self.shortcut.activated.connect(self.addRow)
        self.shortcut = QShortcut(QKeySequence("+"), self)
        self.shortcut.activated.connect(self.increase_playback)
        self.shortcut = QShortcut(QKeySequence("-"), self)
        self.shortcut.activated.connect(self.decrease_playback)

        self.shortcut = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.shortcut.activated.connect(self.next)
        self.shortcut = QShortcut(QKeySequence(Qt.Key_Right), self)
        self.shortcut.activated.connect(self.forwardSlider)
        self.shortcut = QShortcut(QKeySequence(Qt.Key_Left), self)
        self.shortcut.activated.connect(self.backSlider)
        self.shortcut = QShortcut(QKeySequence(Qt.Key_Up), self)
        self.shortcut.activated.connect(self.volumeUp)
        self.shortcut = QShortcut(QKeySequence(Qt.Key_Down), self)
        self.shortcut.activated.connect(self.volumeDown)
        self.shortcut = QShortcut(QKeySequence(Qt.ShiftModifier + Qt.Key_Right), self)
        self.shortcut.activated.connect(self.forwardSlider10)
        self.shortcut = QShortcut(QKeySequence(Qt.ShiftModifier + Qt.Key_Left), self)
        self.shortcut.activated.connect(self.backSlider10)

        self.mediaPlayer.setVideoOutput(self.videoWidget)
        self.mediaPlayer.stateChanged.connect(self.mediaStateChanged)
        self.mediaPlayer.positionChanged.connect(self.positionChanged)
        self.mediaPlayer.positionChanged.connect(self.handleLabel)
        self.mediaPlayer.durationChanged.connect(self.durationChanged)
        self.mediaPlayer.error.connect(self.handleError)

    def openFile(self):
        openVideoDialog = OpenVideoInputDialog(self)
        if openVideoDialog.exec():
            user_id, video_result_id, video_filepath = openVideoDialog.getInputs()

            self.userId = int(user_id) if user_id != "" else -1
            self.videoResultId = int(video_result_id) if video_result_id != "" else -1
            self.video_file_path = video_filepath

            if self.video_file_path == "":
                try:
                    self.video_file_path = download_file_from_s3(self.userId, self.videoResultId, "full_video.ts")
                    fps = get_video_fps(self.video_file_path)
                    self.populateRowsFromApi(self.userId, self.videoResultId, fps)
                except:
                    showErrorDialog("Failed to download video from S3. Check that the video exists and try again.")

            self.mediaPlayer.setMedia(QMediaContent(QUrl.fromLocalFile(self.video_file_path)))
            self.playButton.setEnabled(True)

    def populateRowsFromApi(self, user_id, video_result_id, fps):
        self.clearTable()
        labels = get_labels_from_api(user_id, video_result_id)
        self.colNo = 0
        for label in labels:
            self.addValueToCurrentCell(convert_frame_num_to_time(label["start_frame"], fps))
            self.addValueToCurrentCell(convert_frame_num_to_time(label["end_frame"], fps))
            self.addValueToCurrentCell(label["exercise"])
            self.addValueToCurrentCell(label["view"])
            self.addValueToCurrentCell(str(label["min_reps"]))
            self.addValueToCurrentCell(str(label["reps"]))
            self.addValueToCurrentCell(label["rules"])
            self.addValueToCurrentCell(label["reps_to_judge"])
            self.addValueToCurrentCell(label["notes"])
            self.colNo = 0
            self.rowNo += 1

    def play(self):
        if self.mediaPlayer.state() == QMediaPlayer.PlayingState:
            self.mediaPlayer.pause()
        else:
            self.mediaPlayer.play()

    def _play_video(self):
        if self.is_playing_video and self.video_fps:
            frame_idx = min(self.render_frame_idx + 1, self.frame_count)
            print(frame_idx)

            if frame_idx == self.frame_count:
                self.on_play_video_clicked()
            else:
                self.target_frame_idx = frame_idx

    def style_choice(self, text):
        self.dropDownName = text
        QApplication.setStyle(QStyleFactory.create(text))

    def addStartTime(self):
        self.startTime.setText(self.lbl.text())

    def addEndTime(self):
        self.endTime.setText(self.lbl.text())

    def addRepCount(self):
        self.repCount.setText(self.lbl.text())

    def next(self):
        self.addValueToCurrentCell(self.startTime.text())
        self.addValueToCurrentCell(self.endTime.text())
        self.addValueToCurrentCell(self.iLabel.currentText())
        self.addValueToCurrentCell(self.orientation.currentText())
        self.addValueToCurrentCell(self.minReps.text())
        self.addValueToCurrentCell(self.maxReps.text())
        self.addValueToCurrentCell(self.rules.currentText())
        self.addValueToCurrentCell(self.repsToJudge.text())
        self.colNo = 0
        self.rowNo += 1

    def delete(self):
        index_list = []
        for model_index in self.tableWidget.selectionModel().selectedRows():
            index = QtCore.QPersistentModelIndex(model_index)
            index_list.append(index)

        self.rowNo = self.rowNo - len(index_list)

        for index in index_list:
            self.tableWidget.removeRow(index.row())

    def clearTable(self):
        while self.tableWidget.rowCount() > 0:
            self.tableWidget.removeRow(0)
        self.insertBaseRow()

    def copyRow(self):
        columnCount = self.tableWidget.columnCount()
        for j in range(columnCount):
            if not self.tableWidget.item(self.rowNo - 1, j) is None:
                self.tableWidget.setItem(
                    self.rowNo, j, QTableWidgetItem(self.tableWidget.item(self.rowNo - 1, j).text())
                )
        self.rowNo += 1

    def addRow(self):
        rowCount = self.tableWidget.rowCount()
        self.tableWidget.insertRow(rowCount)

    def increase_playback(self):
        original_position = self.mediaPlayer.position()
        speed_multiplier = round(self.mediaPlayer.playbackRate() + 0.05, 2)
        self.mediaPlayer.setPlaybackRate(speed_multiplier)
        self.mediaPlayer.setPosition(original_position)
        self.update_playback_label()

    def decrease_playback(self):
        if self.mediaPlayer.playbackRate() > 0:
            original_position = self.mediaPlayer.position()
            speed_multiplier = round(self.mediaPlayer.playbackRate() - 0.05, 2)
            self.mediaPlayer.setPlaybackRate(speed_multiplier)
            self.mediaPlayer.setPosition(original_position)
            self.update_playback_label()

    def saveToCsv(self, filepath):
        with open(filepath, "w") as stream:
            print("saving", filepath)
            writer = csv.writer(stream)
            for row in range(self.tableWidget.rowCount()):
                rowdata = []
                for column in range(self.tableWidget.columnCount()):
                    item = self.tableWidget.item(row, column)
                    if item is not None and item != "":
                        rowdata.append(item.text())
                    else:
                        break
                writer.writerow(rowdata)

        labels_df = pd.read_csv(filepath)
        if self.video_file_path:
            labels_df = convert_time_to_frame_num_df(labels_df, self.video_file_path)
            labels_df = labels_df.drop(["start_time", "end_time"], axis=1)

        labels_df = add_labels_column(labels_df)
        labels_df.to_csv(filepath)
        return labels_df

    def exportCsv(self):
        if self.video_file_path:
            self.fName = ((self.video_file_path.rsplit("/", 1)[1]).rsplit(".", 1))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save File", QDir.homePath() + "/" + self.fName + ".csv", "CSV Files(*.csv *.txt)"
        )
        if path:
            self.saveToCsv(path)

    def exportDb(self):
        if self.userId < 0 or self.videoResultId < 0:
            dialog = ExportDBInputDialog()
            if dialog.exec():
                uid, vrid = dialog.getInputs()
                if uid == "" or vrid == "":
                    showDialog("Both user ID and video result ID are required.", success=False)
                    return

                self.userId = int(uid)
                self.videoResultId = int(vrid)
        self.exportAndSendLabelsToDb(self.userId, self.videoResultId)

    def exportAndSendLabelsToDb(self, user_id, video_result_id):
        tmp_dir = os.path.join(self.tmpDir, str(video_result_id))
        temp_csv_fp = os.path.join(tmp_dir, "full_video_labels.csv")
        os.makedirs(tmp_dir, exist_ok=True)

        labels_df = self.saveToCsv(temp_csv_fp)
        errors = send_labels_to_api(user_id, video_result_id, labels_df)
        if errors != "":
            showDialog(errors, success=False)
        else:
            showDialog("Labels uploaded successfully!")

    def addValueToCurrentCell(self, value):
        self.tableWidget.setItem(self.rowNo, self.colNo, QTableWidgetItem(value))
        self.colNo += 1

    def importCSV(self):
        path, _ = QFileDialog.getOpenFileName(self, "Save File", QDir.homePath(), "CSV Files(*.csv *.txt)")
        print(path)
        if path:
            self.clearTable()
            with open(path, "r") as stream:
                print("loading", path)
                reader = csv.reader(stream)
                for i, row in enumerate(reader):
                    if i == 0:
                        continue
                    else:
                        for i in range(8):
                            self.addValueToCurrentCell(row[i])
                        if len(row) == 9:
                            self.tableWidget.setItem(self.rowNo, self.colNo, QTableWidgetItem(row[8]))
                        self.colNo = 0
                        self.rowNo += 1

    def generateReport(self):
        shutil.rmtree(self.tmpDir, ignore_errors=True)
        os.makedirs(self.tmpDir, exist_ok=True)
        self.reportButton.setDisabled(True)
        try:
            if self.userId < 0 or self.videoResultId < 0:
                self.exportDb()
            else:
                self.exportAndSendLabelsToDb(self.userId, self.videoResultId)

            tmp_dir = os.path.join(self.tmpDir, str(self.videoResultId))
            self.setupGenerateReport(self.userId, self.videoResultId, tmp_dir)

            pdf_fp = generate_report(self.tmpDir, str(self.videoResultId), output_pdf_dir=self.tmpDir)
            upload_file_to_s3(self.userId, self.videoResultId, pdf_fp)
            showDialog(f"Report generated at: {pdf_fp} and uploaded to S3!")
        except Exception:
            showDialog(str(traceback.format_exc()), success=False)
        finally:
            self.reportButton.setDisabled(False)

    def setupGenerateReport(self, user_id, video_result_id, output_dir):
        video_ts_path = os.path.join(output_dir, "full_video.ts")
        video_mp4_path = video_ts_path.replace(".ts", ".mp4")
        video_frames_path = os.path.join(output_dir, "full_video_frames")
        download_file_from_s3(user_id, video_result_id, "full_video.ts", video_ts_path)
        download_file_from_s3(
            user_id, video_result_id, "pose_results.json", os.path.join(output_dir, "pose_results.json")
        )

        subprocess.run(["ffmpeg", "-i", video_ts_path, video_mp4_path])
        vid_to_frames(video_ts_path, video_frames_path)

    def insertBaseRow(self):
        self.tableWidget.setColumnCount(9)  # , Start Time, End Time, TimeStamp
        self.tableWidget.setRowCount(500)
        self.rowNo = 1
        self.colNo = 0
        self.tableWidget.setItem(0, 0, QTableWidgetItem("start_time"))
        self.tableWidget.setItem(0, 1, QTableWidgetItem("end_time"))
        self.tableWidget.setItem(0, 2, QTableWidgetItem("exercise"))
        self.tableWidget.setItem(0, 3, QTableWidgetItem("orientation"))
        self.tableWidget.setItem(0, 4, QTableWidgetItem("min_reps"))
        self.tableWidget.setItem(0, 5, QTableWidgetItem("reps"))
        self.tableWidget.setItem(0, 6, QTableWidgetItem("rule"))
        self.tableWidget.setItem(0, 7, QTableWidgetItem("reps_to_judge"))
        self.tableWidget.setItem(0, 8, QTableWidgetItem("notes"))

    def checkTableFrame(self, row, column):
        if (row > 0) and (column < 2):
            item = self.tableWidget.item(row, column)
            if item != (None and ""):
                try:
                    itemFrame = item.text()
                    itemFrame = itemFrame.split(":")
                    frameTime = int(itemFrame[2]) + int(itemFrame[1]) * 60 + int(itemFrame[0]) * 3600
                    elblFrames = self.elbl.text().split(":")
                    elblFrameTime = int(elblFrames[2]) + int(elblFrames[1]) * 60 + int(elblFrames[0]) * 3600
                    self.mediaPlayer.setPosition(frameTime * 1000 + 1 * 60)
                except:
                    self.errorLabel.setText("Some Video Error - Please Recheck Video Imported!")
                    self.errorLabel.setStyleSheet("color: red")

    def mediaStateChanged(self, state):
        if self.mediaPlayer.state() == QMediaPlayer.PlayingState:
            self.playButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.playButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def positionChanged(self, position):
        self.positionSlider.setValue(position)

    def durationChanged(self, duration):
        self.positionSlider.setRange(0, duration)
        mtime = QTime(0, 0, 0, 0)
        mtime = mtime.addMSecs(self.mediaPlayer.duration())
        self.elbl.setText(mtime.toString())

    def setPosition(self, position):
        self.mediaPlayer.setPosition(position)

    def handleError(self):
        self.playButton.setEnabled(False)
        self.errorLabel.setText("Error: " + self.mediaPlayer.errorString())
        self.errorLabel.setStyleSheet("color: red")

    def forwardSlider(self):
        self.mediaPlayer.setPosition(self.mediaPlayer.position() + 1 * 60)

    def forwardSlider10(self):
        self.mediaPlayer.setPosition(self.mediaPlayer.position() + 10 * 60)

    def backSlider(self):
        self.mediaPlayer.setPosition(self.mediaPlayer.position() - 1 * 60)

    def backSlider10(self):
        self.mediaPlayer.setPosition(self.mediaPlayer.position() - 10 * 60)

    def volumeUp(self):
        self.mediaPlayer.setVolume(self.mediaPlayer.volume() + 10)
        print("Volume: " + str(self.mediaPlayer.volume()))

    def volumeDown(self):
        self.mediaPlayer.setVolume(self.mediaPlayer.volume() - 10)
        print("Volume: " + str(self.mediaPlayer.volume()))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    ##################### update Label ##################################
    def handleLabel(self):
        self.lbl.clear()
        mtime = QTime(0, 0, 0, 0)
        self.time = mtime.addMSecs(self.mediaPlayer.position())
        self.lbl.setText(self.time.toString())

    def dropEvent(self, event):
        f = str(event.mimeData().urls()[0].toLocalFile())
        self.loadFilm(f)

    def clickFile(self):
        print("File Clicked")

    def clickExit(self):
        sys.exit()

    def update_playback_label(self):
        self.playbackIndicator.clear()
        self.playbackIndicator.setText("X" + str(self.mediaPlayer.playbackRate()))


App = QApplication(sys.argv)
window = Window()
sys.exit(App.exec())
