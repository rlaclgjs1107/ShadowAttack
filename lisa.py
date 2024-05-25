# -*- coding: utf-8 -*-

import gc
import json
import os
import pickle
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data.dataloader import DataLoader
from torchvision import transforms
from utils import (
    SmoothCrossEntropyLoss,
    draw_shadow,
    judge_mask_type,
    load_mask,
    seed_everything,
    shadow_edge_blur,
)

with open('params.json', 'r') as config:
    params = json.load(config)
    class_n = params['LISA']['class_n']
    device = params['device']
    seed_everything(params['seed'])
    position_list, _ = load_mask()

class Logger:
    def __init__(self, file: str):
        self.file = file
        self.log: list[str] = []

    def add(self, text: str, end: str = "\n", verbose: bool = True):
        if verbose:
            print(text, end=end)
        self.log.append(text+end)

    def save(self):
        with open(self.file, 'w') as f:
            for line in self.log:
                f.write(line)


class TrafficSignDataset(torch.utils.data.Dataset):

    def __init__(self, x, y):
        self.x = x
        self.y = torch.LongTensor(y)

    def __len__(self):
        return len(self.x)

    def __getitem__(self, item):
        _x = transforms.ToTensor()(self.x[item])
        _y = self.y[item]
        return _x, _y


class LisaCNN(nn.Module):

    def __init__(self, n_class):

        super().__init__()
        self.conv1 = nn.Conv2d(3, 64, (8, 8), stride=(2, 2), padding=3)
        self.conv2 = nn.Conv2d(64, 128, (6, 6), stride=(2, 2), padding=0)
        self.conv3 = nn.Conv2d(128, 128, (5, 5), stride=(1, 1), padding=0)
        self.fc = nn.Linear(512, n_class)

    def forward(self, x):

        x = nn.ReLU()(self.conv1(x))
        x = nn.ReLU()(self.conv2(x))
        x = nn.ReLU()(self.conv3(x))
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x


data_transforms = transforms.Compose([
    transforms.ToTensor(),
    # transforms.Normalize(tuple(mean), tuple(std))
])

loss_fun = SmoothCrossEntropyLoss(smoothing=0.1)


def weights_init(m):

    if isinstance(m, nn.Conv2d):
        torch.nn.init.xavier_uniform_(m.weight)
        torch.nn.init.zeros_(m.bias)


def model_epoch(training_model, data_loader, train=False, optimizer=None, scheduler=None):

    loss = acc = 0.0

    for data_batch in data_loader:
        train_predict = training_model(data_batch[0].to(device))
        batch_loss = loss_fun(train_predict, data_batch[1].to(device))
        if train:
            batch_loss.backward()
            optimizer.step()
            optimizer.zero_grad()
        acc += (torch.argmax(train_predict.cpu(), dim=1) == data_batch[1]).sum()
        loss += batch_loss.item() * len(data_batch[1])

    if scheduler:
        scheduler.step()

    return acc, loss


def training(training_model, train_data, train_labels, test_data, test_labels, adv_train=False, logger: Logger = Logger("log.txt")):

    num_epoch, batch_size = 100, 16
    optimizer = torch.optim.SGD(
        training_model.parameters(), lr=0.02, momentum=0.9, weight_decay=5e-4)
    scheduler = torch.optim.lr_scheduler.MultiStepLR(
        optimizer, milestones=[50], gamma=0.2)

    for epoch in range(num_epoch):

        extra_train, extra_labels = adversarial_augmentation(
            train_data, train_labels) if adv_train else (train_data, train_labels)

        train_set = TrafficSignDataset(extra_train, extra_labels)
        test_set = TrafficSignDataset(test_data, test_labels)
        train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
        test_loader = DataLoader(test_set, batch_size=batch_size, shuffle=False)

        epoch_start_time = time.time()

        training_model.train()
        train_acc, train_loss = model_epoch(
            training_model, train_loader, train=True, optimizer=optimizer, scheduler=scheduler)

        training_model.eval()
        with torch.no_grad():
            test_acc, test_loss = model_epoch(training_model, test_loader)

        logger.add(f'[{epoch + 1}/{num_epoch}] {round(time.time() - epoch_start_time, 2)}', end=' ')
        logger.add(f'Train Acc: {round(float(train_acc / train_set.__len__()), 4)}', end=' ')
        logger.add(f'Loss: {round(float(train_loss / train_set.__len__()), 4)}', end=' | ')
        logger.add(f'Test Acc: {round(float(test_acc / test_set.__len__()), 4)}', end=' ')
        logger.add(f'Loss: {round(float(test_loss / test_set.__len__()), 4)}')

        del extra_train, extra_labels, train_set, train_loader
        gc.collect()

    torch.save(training_model.state_dict(),
               f'./model/{"adv_" if adv_train else ""}model_lisa.pth')


def adversarial_augmentation(ori_data_train, ori_labels_train):

    num_data = ori_data_train.shape[0]
    data_train = np.zeros((num_data * 2, 32, 32, 3), np.uint8)
    labels_train = np.zeros(num_data * 2, np.int)
    data_train[0::2] = ori_data_train
    labels_train[0::2] = labels_train[1::2] = ori_labels_train

    for i in range(0, num_data * 2, 2):
        pos_list = position_list[judge_mask_type("LISA", labels_train[i])]
        shadow_image, shadow_area = draw_shadow(
            np.random.uniform(-16, 48, 6), data_train[i], pos_list, np.random.uniform(0.2, 0.7))
        data_train[i + 1] = shadow_edge_blur(shadow_image, shadow_area, 3)

    return data_train, labels_train


def train_model(adv_train=False):

    with open('./dataset/LISA/train.pkl', 'rb') as f:
        train = pickle.load(f)
        train_data, train_labels = train['data'], train['labels']
    with open('./dataset/LISA/test.pkl', 'rb') as f:
        test = pickle.load(f)
        test_data, test_labels = test['data'], test['labels']

    training_model = LisaCNN(n_class=class_n).to(device).apply(weights_init)
    training(training_model, train_data, train_labels, test_data, test_labels, adv_train)


def test_model(adv_model=False, logger: Logger = Logger("log.txt")):

    trained_model = LisaCNN(n_class=class_n).to(device)
    trained_model.load_state_dict(
        torch.load(f'./model/{"adv_" if adv_model else ""}model_lisa.pth',
                   map_location=torch.device(device)))

    with open('./dataset/LISA/test.pkl', 'rb') as f:
        test = pickle.load(f)
        test_data, test_labels = test['data'], test['labels']

    test_set = TrafficSignDataset(test_data, test_labels)
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False)

    trained_model.eval()
    with torch.no_grad():
        test_acc, _ = model_epoch(trained_model, test_loader)

    logger.add(f'Test Acc: {round(float(test_acc / test_set.__len__()), 4)}')


def test_single_image(img_path, ground_truth, adv_model=False, logger: Logger = Logger("log.txt")):

    trained_model = LisaCNN(n_class=class_n).to(device)
    trained_model.load_state_dict(
        torch.load(f'./model/{"adv_" if adv_model else ""}model_lisa.pth',
                   map_location=torch.device(device)))
    trained_model.eval()

    img = cv2.imread(img_path)
    img = cv2.resize(img, (32, 32))
    img = transforms.ToTensor()(img)
    img = img.unsqueeze(0).to(device)

    predict = torch.softmax(trained_model(img)[0], 0)
    index = int(torch.argmax(predict).data)
    confidence = float(predict[index].data)

    logger.add(f'Correct: {index==ground_truth}', end=' ')
    logger.add(f'Predict: {index} Confidence: {confidence*100}%')

    return index, index == ground_truth


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python lisa.py <frames_dir> <log_path>")
        sys.exit(1)
    
    frames_dir = sys.argv[1]
    logger = Logger(sys.argv[2])
    
    images = os.listdir(f"./videos/{frames_dir}")
    images.sort(key=lambda x: int(x.split(".")[0]))
    logger.add(f"Total frames: {len(images)}")
    
    fail = 0
    failed_images = []
    for img in images:
        idx, res = test_single_image(f"./videos/{frames_dir}/{img}", 9, adv_model=False, logger=logger)
        if res == False:
            fail += 1
            failed_images.append(img)
    
    logger.add(f"Failed: {fail}")
    logger.add(str(failed_images))
    logger.save()
