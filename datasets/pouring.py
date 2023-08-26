# coding=utf-8
import os
import math
import pickle
import torch
import torch.nn.functional as F
from torchvision.io import read_video
import numpy as np

import random

import utils.logging as logging
from datasets.data_augment import create_data_augment, create_ssl_data_augment

logger = logging.get_logger(__name__)

class Pouring(torch.utils.data.Dataset):
    def __init__(self, cfg, split, mode="auto", sample_all=False):
        assert split in ["train", "val", "test"]
        self.cfg = cfg
        self.split = split
        if mode == "auto":
            self.mode = "train" if self.split=="train" else "eval"
        else:
            self.mode = mode
        self.sample_all = sample_all
        self.num_contexts = cfg.DATA.NUM_CONTEXTS

        with open(os.path.join(cfg.PATH_TO_DATASET, split+'.pkl'), 'rb') as f:
            self.dataset = pickle.load(f)

        if not self.sample_all:
            logger.info(f"{len(self.dataset)} {self.split} samples of Pouring dataset have been read.")
            seq_lens = [data['seq_len'] for data in self.dataset]
            hist, bins = np.histogram(seq_lens, bins='auto')
            print(list(bins.astype(np.int)))
            print(list(hist))

        self.num_frames = cfg.TRAIN.NUM_FRAMES
        self.num_segments = cfg.TRAIN.NUM_SEGMENTS
        self.overlap_rate = cfg.TRAIN.OVERLAP_RATE
        # Perform data-augmentation
        if self.cfg.SSL and self.mode=="train":
            self.data_preprocess = create_ssl_data_augment(cfg, augment=True)
        elif self.mode=="train":
            self.data_preprocess = create_data_augment(cfg, augment=True)
        else:
            self.data_preprocess = create_data_augment(cfg, augment=False)


    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, index):
        id = self.dataset[index]["id"]
        name = self.dataset[index]["name"]
        frame_label = self.dataset[index]["frame_label"]
        seq_len = self.dataset[index]["seq_len"]
        video_file = os.path.join(self.cfg.PATH_TO_DATASET, self.dataset[index]["video_file"])
        video, _, info = read_video(video_file, pts_unit='sec')
        video = video.permute(0,3,1,2).float() / 255.0
        assert len(video) == seq_len
        assert len(video) == len(frame_label)
        steps = self.sample_frames(seq_len, self.num_frames)

        labels = frame_label[steps.long()]
        video = video[steps.long()]
        video = self.data_preprocess(video)

        if self.cfg.DATA.ANNOTATION == 'raw':
            bridges = self.bridge_construct(steps, self.overlap_rate, self.num_segments)
        else:
            bridges = self.bridge_phase(labels)

        return video, labels, torch.tensor(seq_len), bridges, name, id

    def sample_frames(self, seq_len, num_frames):
        if seq_len >= num_frames:
            steps = torch.randperm(seq_len) 
            steps = torch.sort(steps[:num_frames])[0] #0-value,1-index
        else:
            steps = torch.randint(low=0, high=seq_len, size=(num_frames,))
            steps = torch.sort(steps)[0] 
        return steps

    def bridge_construct(self, steps, overlap_rate, num_segments):
        avg_len = int(len(steps) / num_segments)
        half_lap = int(avg_len*overlap_rate / (2-overlap_rate))
        bridges = torch.empty(num_segments,3)
        for i in range(num_segments):
            if i == 0:
                bridge_head = random.randint(0,half_lap)  # include a,b
                bridge_tail = avg_len + random.randint(0,half_lap)
            elif i == num_segments-1:
                bridge_head = i * avg_len - random.randint(0,half_lap)
                bridge_tail =  len(steps) - random.randint(1,half_lap)
            else:
                bridge_head = i * avg_len - random.randint(0,half_lap)
                bridge_tail = (i+1) * avg_len + random.randint(0,half_lap)
            bridge_point = bridge_head + random.randint(1,avg_len-half_lap-1)
            bridges[i] = torch.tensor([bridge_head,bridge_point,bridge_tail])
        return bridges


    def bridge_phase(self,frame_label):
        bridges = torch.empty(0,3)
        frame_list = frame_label.tolist()
        groups = list(set(frame_list)) 
        for group in groups:
            start = frame_list.index(group) 
            end = len(frame_list) - frame_list[::-1].index(group) -1
            if end - start <= 1: continue
            bridge_point = random.randint(start+1,end-1)
            cur = torch.tensor([[start,bridge_point,end]])
            bridges = torch.cat((bridges,cur),dim=0)

        inx = random.randint(0, len(bridges)-2)
        assert len(bridges)>1
        return bridges[inx:inx+2]
    

