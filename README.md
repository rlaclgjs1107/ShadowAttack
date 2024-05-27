# CSED415: Computer Security
Professor: Seulbae Kim  
Team: whysw (Chiheon Kim, Sungjae Cho)

## Adversarial Attacks on Traffic Sign Recognition in a Physical Domain
> Note: This repository is forked from the original author's repository.

Reproduce and further explore ShadowAttack([paper](https://arxiv.org/abs/2203.03818) / [github](https://github.com/hncszyq/ShadowAttack))

## New features

- Seed Fix  
  Add `seed_everything()` for reliable reproductions. A seed can be specified in `params.json`.  

- Video Preprocess  
  `video_preprocess.py` saves cropped traffic sign images from each frame of given video. (The video should be located under `videos/` directory and have `.mp4` format.) It requires a JSON file exported from "Lable Studio", where you can manually label a traffic sign with a rectangle box. With the key frame information in the JSON file, it calculates interpolation and finds the position of the traffic sign in each frame. Then it saves the images under `videos/<video_file_name>-frames/<frame#>.jpg`.  
  ```sh
  python video_preprocess.py test.mp4
  ```

- Automated `single_image_test()` for given directory  
  To test every single image saved under `videos/<video_file_name>-frames/`, `lisa.py` is slightly modified. Given a directory name under `videos/`, it iteratively test each image and saves all the results in specified log file.  
  ```
  python lisa.py test-frames test.log
  ```
