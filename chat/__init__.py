"""
对话模块

这个文件是 Python 包的初始化文件
当使用 "from chat import xxx" 时，Python 会先执行这个文件
"""

# 从当前目录的 session.py 文件中导入 ChatSession 类
# 这样用户可以直接使用 "from chat import ChatSession" 而不需要 "from chat.session import ChatSession"
from .session import ChatSession

# __all__ 定义了当使用 "from chat import *" 时，会导入哪些名称
# 这是一种良好的实践，明确声明模块的公开接口
__all__ = ['ChatSession']
