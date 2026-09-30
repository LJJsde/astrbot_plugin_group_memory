# astrbot_plugin_group_memory

让 AstrBot 大模型按需读取 MySQL 中的群成员档案信息，从而更「认识」群成员，回复更有真人感，同时避免把所有成员信息塞进 prompt 浪费 token。

## 功能

- 通过 **function-calling 工具** `query_group_member`，让大模型在群聊中按需查询成员档案（QQ/昵称/群名片/职业/地区/爱好/备注）。
- 查询结果回填给大模型，**用真实数据改变它的回复**（例如正确称呼某人、引用其爱好）。
- 提供 **WebUI 管理页**，可手工新增/编辑/删除成员档案。
- 插件首次启动时自动建表（幂等）。

## 架构

- 数据库：MySQL
- 数据层：SQLAlchemy 2.x（异步）+ asyncmy 方言
- 表：`member_profile`（见下方结构）

## 安装

1. 将本插件放入 AstrBot 的 `data/plugins/` 目录。
2. 在 AstrBot WebUI 的「插件」页启用本插件，并配置 MySQL 连接信息（主机、端口、账号、密码、库名）。
3. 插件首次启动会自动建表。

## MySQL 连接（配置项）

在插件 `_conf_schema.json` 中配置，默认：

- `db_host`: `mysql`（与 AstrBot 同 docker 网络时填服务名）
- `db_port`: `3306`
- `db_user`: `root`
- `db_password`: （空）
- `db_name`: `group_memory`

## 表结构

```sql
CREATE TABLE member_profile (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    qq BIGINT NOT NULL UNIQUE,
    nickname VARCHAR(100),
    card_name VARCHAR(100),
    occupation VARCHAR(100),
    location VARCHAR(100),
    hobby TEXT,
    remark TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

## 使用方法

- 群聊中直接提问（例如「刚才说话的人叫什么？」「群里有没有谁喜欢摄影？」），支持 function-calling 的模型会自动调用工具查询。
- 管理页：插件详情页 → 群成员记忆管理，可增删改成员档案。
- 测试指令：`/gm_show <qq>` 可手动查看某成员档案。

## 依赖

见 `requirements.txt`：

```
SQLAlchemy>=2.0.0
asyncmy>=0.2.9
```

### 国内 pip 源（可选）

若安装依赖时网络较慢，可在安装时使用国内镜像：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

或配置 `~/.pip/pip.conf`：

```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
```

其他常用国内源：

- 清华：`https://pypi.tuna.tsinghua.edu.cn/simple`
- 阿里云：`https://mirrors.aliyun.com/pypi/simple/`
- 中科大：`https://pypi.mirrors.ustc.edu.cn/simple/`

## 后续规划

- 第一阶段（当前）：静态成员档案 + 手工录入 + function-calling 查询。
- 后续：接入 embedding 做语义触发、长期记忆、自动抓取群消息整理等。

## License

MIT
