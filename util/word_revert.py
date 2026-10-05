# Modified distribution: 2026-10-06. License: GPL-3.0.
# Based on ularch/Easy_Cidaren and github123666/cidaren.
import spacy
import os
from functools import lru_cache
from threading import Lock

from api.basic_api import use_api_get_prototype
from log.log import Log

# 使用本地目录的模型，便于打包
current_dir = os.path.dirname(os.path.abspath(__file__))
# 上一级目录
parent_dir = os.path.dirname(current_dir)
model_path = os.path.join(parent_dir, 'en_core_web_sm')
module = Log("word_revert")
_model = None
_model_lock = Lock()

if not os.path.exists(model_path):
    module.logger.error(f"模型文件夹不存在: {model_path}")
elif not os.listdir(model_path):
    module.logger.error(f"模型文件夹为空: {model_path}")


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = spacy.load(model_path)
                module.logger.info('词形模型已加载，后续复用')
    return _model


@lru_cache(maxsize=1024)
def _local_lemma(word):
    nlp = get_model()
    with _model_lock:
        doc = nlp(word)
        return doc[0].lemma_ if len(doc) else word


def word_revert(word: str) -> str:
    """
    优先使用模型转原型
    :param word: 目标单词
    :return: 原型
    """
    try:
        return _local_lemma(word.strip().lower())
    except Exception as e:
        module.logger.error(f"模型加载失败")
        module.logger.error(e)
        return use_api_get_prototype(word)


if __name__ == '__main__':
    print(word_revert('done'))
