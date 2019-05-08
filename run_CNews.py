import random
import numpy as np
import time
from tqdm import tqdm
import os

import torch
import torch.nn as nn
from torch.utils.data import (
    DataLoader, RandomSampler, SequentialSampler, TensorDataset)


from pytorch_pretrained_bert.tokenization import BertTokenizer
from pytorch_pretrained_bert.modeling import BertForSequenceClassification, BertConfig, WEIGHTS_NAME, CONFIG_NAME
from pytorch_pretrained_bert.optimization import BertAdam, warmup_linear

from Utils import utils
from BertOrigin import args

from Processors.NewsProcessor import NewsProcessor, cnews_data


def main(config):

    if not os.path.exists(config.output_dir):
        os.makedirs(config.output_dir)

    if not os.path.exists(config.cache_dir):
        os.makedirs(config.cache_dir)

    output_model_file = os.path.join(config.output_dir, WEIGHTS_NAME)  # 模型输出文件
    output_config_file = os.path.join(config.output_dir, CONFIG_NAME)

    device, n_gpu = utils.get_device()  # 设备准备

    config.train_batch_size = config.train_batch_size // config.gradient_accumulation_steps

    """ 设定随机种子 """
    random.seed(config.seed)
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    if n_gpu > 0:
        torch.cuda.manual_seed_all(config.seed)

    """ 数据准备 """
    processor = NewsProcessor()  # processor 选择
    tokenizer = BertTokenizer.from_pretrained(
        "/home/songyingxin/datasets/pytorch-bert/vocabs/bert-base-chinese-vocab.txt", do_lower_case=config.do_lower_case)  # 分词器选择

    train_dataloader, dev_dataloader, test_dataloader, label_list, train_examples_len = cnews_data(
        config.data_dir, tokenizer, processor, config.max_seq_length, config.train_batch_size, config.dev_batch_size, config.test_batch_size)

    num_labels = len(label_list)
    num_train_optimization_steps = int(
        train_examples_len / config.train_batch_size / config.gradient_accumulation_steps) * config.num_train_epochs

    # 模型准备
    model = BertForSequenceClassification.from_pretrained(
        "/home/songyingxin/datasets/pytorch-bert/bert-base-chinese", cache_dir=config.cache_dir, num_labels=num_labels)
    model.to(device)

    # 优化器
    param_optimizer = list(model.named_parameters())
    no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(
            nd in n for nd in no_decay)], 'weight_decay': 0.01},
        {'params': [p for n, p in param_optimizer if any(
            nd in n for nd in no_decay)], 'weight_decay': 0.0}
    ]
    optimizer = BertAdam(optimizer_grouped_parameters,
                         lr=config.learning_rate,
                         warmup=config.warmup_proportion,
                         t_total=num_train_optimization_steps)

    # 损失函数
    criterion = nn.CrossEntropyLoss()
    criterion = criterion.to(device)

    best_dev_loss = float('inf')
    for epoch in range(int(config.num_train_epochs)):
        start_time = time.time()
        train_loss, train_acc, train_report = train(
            model, train_dataloader, optimizer, criterion, config.gradient_accumulation_steps, device, label_list)

        dev_loss, dev_acc, dev_report = evaluate(
            model, dev_dataloader, criterion, device, label_list)

        end_time = time.time()

        epoch_mins, epoch_secs = utils.epoch_time(start_time, end_time)

        print(
            f'---------------- Epoch: {epoch+1:02} | Epoch Time: {epoch_mins}m {epoch_secs}s ----------')
        print("-------------- Train -------------")
        print(f'\t \t Loss: {train_loss:.3f} |  Acc: {train_acc*100: .2f} %')
        print(train_report)
        print("-------------- Dev -------------")
        print(f'\t \t Loss: {dev_loss: .3f} | Acc: {dev_acc*100: .2f} %')
        print(dev_report)

        # 模型保存
        if dev_loss < best_dev_loss:
            best_dev_loss = dev_loss

            model_to_save = model.modules if hasattr(
                model, 'module') else model
            torch.save(model_to_save.state_dict(), output_model_file)
            with open(output_config_file, 'w') as f:
                f.write(model_to_save.config.to_json_string())

    bert_config = BertConfig(output_config_file)
    model = BertForSequenceClassification(bert_config, num_labels=num_labels)
    model.load_state_dict(torch.load(output_model_file))
    model.to(device)

    # test the model
    test_loss, test_acc, test_report = evaluate(
        model, test_dataloader, criterion, device, label_list)
    print("-------------- Test -------------")
    print(f'\t \t Loss: {test_loss: .3f} | Acc: {test_acc*100: .2f} %')
    print(test_report)


if __name__ == "__main__":

    data_dir = "/home/songyingxin/datasets/cnews"
    output_dir = ".output"
    cache_dir = ".cache"
    main(args.get_args(data_dir, output_dir, cache_dir))
