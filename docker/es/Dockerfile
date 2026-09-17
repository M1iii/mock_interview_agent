# Elasticsearch 8.19.10 + IK 中文分词插件（本地 zip 安装，零网络依赖；方案对齐电商问数项目）
# 说明：构建时用本地 plugins/ 下的 zip，规避 GitHub release 下载失败风险
FROM elasticsearch:8.19.10

USER root

COPY plugins/elasticsearch-analysis-ik-8.19.10.zip /tmp/

RUN /usr/share/elasticsearch/bin/elasticsearch-plugin install --batch \
    file:///tmp/elasticsearch-analysis-ik-8.19.10.zip

RUN chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/plugins

USER elasticsearch
