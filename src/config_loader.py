import json
import logging
import os
from typing import Dict, Any

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_config(config_path: str = "./config.json") -> Dict[str, Any]:
    """加载配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        full_config = json.load(f)
    
    # 从配置文件中获取当前环境，如果没有则从环境变量获取，最后使用默认环境
    env = full_config.get('current_env', os.getenv('ENVIRONMENT', full_config.get('default_env', 'development')))
    
    # 根据环境选择配置
    if env in full_config:
        config = full_config[env]
        logger.info(f"使用 {env} 环境配置，嵌入模型提供商: {config['embedding_model']['provider']}")
    else:
        # 如果指定的环境不存在，使用默认环境
        default_env = full_config.get('default_env', 'development')
        config = full_config.get(default_env, full_config)  # 如果连默认环境都没有，则使用整个配置
        logger.info(f"环境 {env} 不存在，使用默认环境 {default_env}，嵌入模型提供商: {config['embedding_model']['provider']}")
    
    # 将环境信息添加到配置中，方便后续使用
    config['environment'] = env
    
    return config