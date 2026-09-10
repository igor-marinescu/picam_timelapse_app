# picam_timelapse_app Requirements

## General description

"picam_timelapse_app" is a Python+Flask application developed to run on Raspberry Pi Zero board and to make timelapse videos (photos) using Picamera2 Python library.
The device does not have a display or a "viewfinder", the device must be able also to do a video live streaming to allow the user (using another device, for example smartphone) to adjust the focus of the lences and other optical settings.

## Detailed description

1. There is a Raspberry Pi Zero with a Raspberry Pi Camera attached. There is no display. The user interaction is done over a Web Interface.
2. I need an application developed in Python+Flask which allows the following:
- Do a video live streaming, this will allow the user to adjust the optical settings using the Web Interface as a "viewfinder".
- Allow the user to configure the time-interval of the timelapse video (how often to take photos) using the Web Interface.
- Allow the user to configure other settings (Exposure time, Gain, White balance, Colour saturation, Sharpness).
- Take photos at a configurable interval and save them to a local folder using a timestamp as a filename. (The photos will be uploaded later and converted to a video, but this is not a part of this application.)

### Status machine

The application can be in one of the three states:
1. Idle (doing nothing), "Settings and Control" is the main Web page.
2. Timelapse Process (doing timelapse photos), "Timelapse Process" is the Web page.
3. Video Live Streaming (doing video live streaming), "Video Live Streaming" is the Web page.

### WebPages

The application has three web-pages:
1. "Settings and Control", allows the User the following:
- Configure the time-interval of the timelapse video (how often to take photos).
- Configure other settings (Exposure time, Gain, White balance, Colour saturation, Sharpness).
- Button to start taking timelapse photos with configured time-interval: goto "Timelapse Process" state.
- Button to start video live streaming (allow the user to adjust the optical settings): goto "Video Live Streaming" state.
2. "Timelapse Process", indicates the device is in the process of taking timelapse photo, allows the User to do the following:
- Displays info: how many photos were taken, how long (in time) since started, time-interval configured.
- Button to show the last taken picture.
- Button to stop the timelapse and goto "Settings and Control" idle state.
3. "Video Live Streaming", device is doing video live streaming, allows the User to do the following:
- Displays "live" the image from camera.
- Button to stop video live streaming and goto "Settings and Control" idle state.

## Extra requirement

- Generate a README.md file containing detailed instructions including how to deploy the application on Raspbbery Pi.