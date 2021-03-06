# Copyright 2020 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================

"""train bert network without lossscale"""

import os
import pytest
import numpy as np
from numpy import allclose
import mindspore.common.dtype as mstype
import mindspore.dataset.engine.datasets as de
import mindspore.dataset.transforms.c_transforms as C
from mindspore import context
from mindspore.common.tensor import Tensor
from mindspore.train.model import Model
from mindspore.train.callback import Callback, LossMonitor
from mindspore.train.loss_scale_manager import DynamicLossScaleManager
from mindspore.model_zoo.Bert_NEZHA import BertConfig, BertNetworkWithLoss, BertTrainOneStepWithLossScaleCell
from mindspore.nn.optim import Momentum
from mindspore import log as logger
_current_dir = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = ["/home/workspace/mindspore_dataset/bert/example/examples.tfrecord"]
SCHEMA_DIR = "/home/workspace/mindspore_dataset/bert/example/datasetSchema.json"

def get_config(version='base', batch_size=1):
    """get config"""
    if version == 'base':
        bert_config = BertConfig(
            batch_size=batch_size,
            seq_length=128,
            vocab_size=21136,
            hidden_size=768,
            num_hidden_layers=2,
            num_attention_heads=12,
            intermediate_size=3072,
            hidden_act="gelu",
            hidden_dropout_prob=0.1,
            attention_probs_dropout_prob=0.1,
            max_position_embeddings=512,
            type_vocab_size=2,
            initializer_range=0.02,
            use_relative_positions=True,
            input_mask_from_dataset=True,
            token_type_ids_from_dataset=True,
            dtype=mstype.float32,
            compute_type=mstype.float32)
    elif version == 'large':
        bert_config = BertConfig(
            batch_size=batch_size,
            seq_length=128,
            vocab_size=21136,
            hidden_size=1024,
            num_hidden_layers=2,
            num_attention_heads=16,
            intermediate_size=4096,
            hidden_act="gelu",
            hidden_dropout_prob=0.0,
            attention_probs_dropout_prob=0.0,
            max_position_embeddings=512,
            type_vocab_size=2,
            initializer_range=0.02,
            use_relative_positions=True,
            input_mask_from_dataset=True,
            token_type_ids_from_dataset=True,
            dtype=mstype.float32,
            compute_type=mstype.float16)
    elif version == 'large_mixed':
        bert_config = BertConfig(
            batch_size=batch_size,
            seq_length=128,
            vocab_size=21136,
            hidden_size=1024,
            num_hidden_layers=24,
            num_attention_heads=16,
            intermediate_size=4096,
            hidden_act="gelu",
            hidden_dropout_prob=0.0,
            attention_probs_dropout_prob=0.0,
            max_position_embeddings=512,
            type_vocab_size=2,
            initializer_range=0.02,
            use_relative_positions=True,
            input_mask_from_dataset=True,
            token_type_ids_from_dataset=True,
            dtype=mstype.float32,
            compute_type=mstype.float32)
    else:
        bert_config = BertConfig(batch_size=batch_size)
    return bert_config

def me_de_train_dataset():
    """test me de train dataset"""
    # apply repeat operations
    repeat_count = 1
    ds = de.TFRecordDataset(DATA_DIR, SCHEMA_DIR, columns_list=["input_ids", "input_mask", "segment_ids",
                                                               "next_sentence_labels", "masked_lm_positions",
                                                               "masked_lm_ids", "masked_lm_weights"], shuffle=False)
    type_cast_op = C.TypeCast(mstype.int32)
    ds = ds.map(input_columns="masked_lm_ids", operations=type_cast_op)
    ds = ds.map(input_columns="masked_lm_positions", operations=type_cast_op)
    ds = ds.map(input_columns="next_sentence_labels", operations=type_cast_op)
    ds = ds.map(input_columns="segment_ids", operations=type_cast_op)
    ds = ds.map(input_columns="input_mask", operations=type_cast_op)
    ds = ds.map(input_columns="input_ids", operations=type_cast_op)
    # apply batch operations
    batch_size = int(os.getenv('BATCH_SIZE', '16'))
    ds = ds.batch(batch_size, drop_remainder=True)
    ds = ds.repeat(repeat_count)
    return ds

def weight_variable(shape):
    """weight variable"""
    np.random.seed(1)
    ones = np.random.uniform(-0.1, 0.1, size=shape).astype(np.float32)
    return Tensor(ones)

class ModelCallback(Callback):
    def __init__(self):
        super(ModelCallback, self).__init__()
        self.loss_list = []
        self.overflow_list = []
        self.lossscale_list = []

    def step_end(self, run_context):
        cb_params = run_context.original_args()
        self.loss_list.append(cb_params.net_outputs[0])
        self.overflow_list.append(cb_params.net_outputs[1])
        self.lossscale_list.append(cb_params.net_outputs[2])

@pytest.mark.level0
@pytest.mark.platform_arm_ascend_training
@pytest.mark.platform_x86_ascend_training
@pytest.mark.env_onecard
def test_bert_tdt():
    """test bert tdt"""
    context.set_context(mode=context.GRAPH_MODE, device_target="Ascend", reserve_class_name_in_scope=False)
    context.set_context(enable_task_sink=True)
    context.set_context(enable_loop_sink=True)
    context.set_context(enable_mem_reuse=True)
    ds = me_de_train_dataset()
    version = os.getenv('VERSION', 'large')
    batch_size = int(os.getenv('BATCH_SIZE', '16'))
    config = get_config(version=version, batch_size=batch_size)
    netwithloss = BertNetworkWithLoss(config, True)
    optimizer = Momentum(netwithloss.trainable_params(), learning_rate=2e-5, momentum=0.9)
    scale_window = 3
    scale_manager = DynamicLossScaleManager(2**32, 2, scale_window)
    netwithgrads = BertTrainOneStepWithLossScaleCell(netwithloss, optimizer=optimizer, scale_update_cell=scale_manager.get_update_cell())
    netwithgrads.set_train(True)
    model = Model(netwithgrads)
    callback = ModelCallback()
    params = netwithloss.trainable_params()
    for param in params:
        value = param.default_input
        name = param.name
        if isinstance(value, Tensor):
            if name.split('.')[-1] in ['weight']:
                if name.split('.')[-3] in ['cls2']:
                    logger.info("***************** BERT param name is 1 {}".format(name))
                    param.default_input = weight_variable(value.asnumpy().shape)
                else:
                    logger.info("***************** BERT param name is 2 {}".format(name))
                    tempshape = value.asnumpy().shape
                    shape = (tempshape[1], tempshape[0])
                    weight_value = weight_variable(shape).asnumpy()
                    param.default_input = Tensor(np.transpose(weight_value, [1, 0]))
            else:
                logger.info("***************** BERT param name is 3 {}".format(name))
                param.default_input = weight_variable(value.asnumpy().shape)
    model.train(ds.get_repeat_count(), ds, callbacks=callback, dataset_sink_mode=False)

    # assertion occurs while the loss_scale value is wrong
    count = 0
    for i in range(len(callback.overflow_list)):
        if callback.overflow_list[i] == Tensor(True, mstype.bool_) and i > 0:
            count = 0
            assert callback.lossscale_list[i] == callback.lossscale_list[i - 1] * Tensor(0.5, mstype.float32)
        if callback.overflow_list[i] == Tensor(False, mstype.bool_):
            count = count + 1
            if count == scale_window:
                count = 0
                assert callback.lossscale_list[i] == callback.lossscale_list[i - 1] * Tensor(2.0, mstype.float32)


if __name__ == '__main__':
    test_bert_tdt()
