"""华为云 SDK 封装：统一凭证、项目管理、各服务客户端工厂。

用于：OCR 照片审核、RDS/Redis 开通脚本。凭证从 .env 读取（HW_AK/HW_SK/HW_REGION）。
"""
from __future__ import annotations

from .config import settings


def base_credentials():
    """无 project_id 的凭证（用于 IAM 全局服务）。"""
    from huaweicloudsdkcore.auth.credentials import BasicCredentials

    return BasicCredentials(settings.huawei_ak, settings.huawei_sk)


_project_id_cache: str | None = None


def get_project_id() -> str:
    """获取项目 ID：优先读 .env 的 HW_PROJECT_ID，未配置才走"取第一个项目"兜底（带缓存）。"""
    global _project_id_cache
    if _project_id_cache:
        return _project_id_cache

    if settings.huawei_project_id:
        _project_id_cache = settings.huawei_project_id
        return _project_id_cache

    from huaweicloudsdkiam.v3 import IamClient, KeystoneListAuthProjectsRequest
    from huaweicloudsdkiam.v3.region.iam_region import IamRegion

    client = IamClient.new_builder() \
        .with_credentials(base_credentials()) \
        .with_region(IamRegion.value_of(settings.huawei_region)) \
        .build()
    resp = client.keystone_list_auth_projects(KeystoneListAuthProjectsRequest())
    if not resp.projects:
        raise RuntimeError("当前账号下没有可用项目，请先在控制台创建项目")
    _project_id_cache = resp.projects[0].id
    return _project_id_cache


def project_credentials():
    """带 project_id 的凭证（用于 OCR/RDS/DCS/VPC 等 region 级服务）。"""
    from huaweicloudsdkcore.auth.credentials import BasicCredentials

    return BasicCredentials(settings.huawei_ak, settings.huawei_sk, get_project_id())


def ocr_extract_text(image_base64: str) -> str:
    """调用华为云通用文字识别，返回识别出的全部文字。"""
    from huaweicloudsdkocr.v1 import OcrClient
    from huaweicloudsdkocr.v1.model import GeneralTextRequestBody, RecognizeGeneralTextRequest
    from huaweicloudsdkocr.v1.region.ocr_region import OcrRegion

    client = OcrClient.new_builder() \
        .with_credentials(project_credentials()) \
        .with_region(OcrRegion.value_of(settings.huawei_region)) \
        .build()
    request = RecognizeGeneralTextRequest()
    request.body = GeneralTextRequestBody(image=image_base64)
    response = client.recognize_general_text(request)
    return "".join(b.words for b in response.result.words_block_list)


def vpc_client():
    from huaweicloudsdkvpc.v2 import VpcClient
    from huaweicloudsdkvpc.v2.region.vpc_region import VpcRegion

    return VpcClient.new_builder() \
        .with_credentials(project_credentials()) \
        .with_region(VpcRegion.value_of(settings.huawei_region)) \
        .build()


def rds_client():
    from huaweicloudsdkrds.v3 import RdsClient
    from huaweicloudsdkrds.v3.region.rds_region import RdsRegion

    return RdsClient.new_builder() \
        .with_credentials(project_credentials()) \
        .with_region(RdsRegion.value_of(settings.huawei_region)) \
        .build()


def dcs_client():
    from huaweicloudsdkdcs.v2 import DcsClient
    from huaweicloudsdkdcs.v2.region.dcs_region import DcsRegion

    return DcsClient.new_builder() \
        .with_credentials(project_credentials()) \
        .with_region(DcsRegion.value_of(settings.huawei_region)) \
        .build()