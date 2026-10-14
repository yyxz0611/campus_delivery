"""通过华为云 API 一键开通 RDS（MySQL）与 DCS（Redis）实例。

用法：
  python scripts/provision.py probe                         # 列出当前账号下可开通资源（只读）
  python scripts/provision.py create-rds  --apply           # 创建 RDS 实例（默认 dry_run=True 演练）
  python scripts/provision.py create-dcs  --apply           # 创建 Redis 实例
  python scripts/provision.py wait RDS_xxx                  # 轮询状态直到 ACTIVE 并打印连接串

凭证与 region 从 .env 读取（HW_AK/HW_SK/HW_REGION）。
需要参数在 .env 配置：RDS_FLAVOR_REF / RDS_PASSWORD / RDS_AZ / DCS_SPEC_CODE / DCS_PASSWORD 等。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import huawei  # noqa: E402
from app.config import settings  # noqa: E402


def _cmd_probe(args) -> int:
    print(f"region: {settings.huawei_region}")
    print(f"project_id: {huawei.get_project_id()}")
    print()

    print("=== VPC（默认 vpc）===")
    from huaweicloudsdkvpc.v2 import ListVpcsRequest

    vpcs = huawei.vpc_client().list_vpcs(ListVpcsRequest()).vpcs
    for v in vpcs[:20]:
        print(f"  vpc_id={v.id}  name={v.name}  cidr={v.cidr}")
    print()

    print("=== Subnet（第一个 VPC）===")
    if vpcs:
        from huaweicloudsdkvpc.v2 import ListSubnetsRequest

        subnets = huawei.vpc_client().list_subnets(
            ListSubnetsRequest(vpc_id=vpcs[0].id)
        ).subnets
        for s in subnets[:20]:
            print(f"  subnet_id={s.id}  name={s.name}  cidr={s.cidr}")
    print()

    print("=== RDS Flavor（MySQL 8.0，按 region 过滤）===")
    from huaweicloudsdkrds.v3 import ListFlavorsRequest

    flavors = huawei.rds_client().list_flavors(
        ListFlavorsRequest(database_name="MySQL", version_name="8.0")
    ).flavors
    for f in flavors[:20]:
        print(f"  spec_code={f.spec_code}  vcpu={f.vcpus}  ram={f.ram}GB")
    print()

    print("=== DCS Flavor（Redis 5.0）===")
    from huaweicloudsdkdcs.v2 import ListFlavorsRequest as DcsListFlavorsRequest

    dcs_flavors = huawei.dcs_client().list_flavors(
        DcsListFlavorsRequest(engine="Redis", engine_version="5.0", cache_mode="single", capacity=1)
    ).flavors
    for f in (dcs_flavors or [])[:10]:
        print(f"  spec_code={f.spec_code}  engine={f.engine}  cache_mode={f.cache_mode}")
    return 0


def _create_subnet(args) -> int:
    name = os.getenv("SUBNET_NAME", "campus-subnet")
    cidr = os.getenv("SUBNET_CIDR", "")
    gateway_ip = os.getenv("SUBNET_GATEWAY_IP", "")
    az = os.getenv("SUBNET_AZ", "")
    vpc_id = os.getenv("SUBNET_VPC_ID") or args.vpc_id

    if not vpc_id:
        # 自动取 VPC 列表第一个
        from huaweicloudsdkvpc.v2 import ListVpcsRequest

        vpcs = huawei.vpc_client().list_vpcs(ListVpcsRequest()).vpcs
        if not vpcs:
            print("当前账号下没有可用 VPC")
            return 1
        vpc_id = vpcs[0].id
        print(f"未指定 SUBNET_VPC_ID，自动使用 VPC: {vpcs[0].name} ({vpc_id})")

    if not cidr:
        # 在 192.168.0.0/16 下默认取 192.168.1.0/24
        cidr = os.getenv("SUBNET_CIDR_DEFAULT", "192.168.1.0/24")
        print(f"未指定 SUBNET_CIDR，自动使用 {cidr}（确保落在 VPC 网段 192.168.0.0/16 内）")
    if not az:
        az = f"{settings.huawei_region}a"
        print(f"未指定 SUBNET_AZ，自动使用 {az}")
    if not gateway_ip:
        # 默认网关取 cidr 的第一个可用地址
        base = cidr.split("/")[0].rsplit(".", 1)[0]
        gateway_ip = f"{base}.1"
        print(f"未指定 SUBNET_GATEWAY_IP，自动使用 {gateway_ip}")

    from huaweicloudsdkvpc.v2.model import (
        CreateSubnetOption,
        CreateSubnetRequest,
        CreateSubnetRequestBody,
    )

    option = CreateSubnetOption(
        name=name, cidr=cidr, vpc_id=vpc_id, gateway_ip=gateway_ip,
        availability_zone=az, dhcp_enable=True,
    )
    resp = huawei.vpc_client().create_subnet(CreateSubnetRequest(
        body=CreateSubnetRequestBody(subnet=option),
    ))
    sub = resp.subnet
    print(f"subnet_id={sub.id}  name={sub.name}  cidr={sub.cidr}  gateway={sub.gateway_ip}  vpc_id={sub.vpc_id}")
    print(f"\n回填到 .env：")
    print(f"  SUBNET_VPC_ID={sub.vpc_id}")
    print(f"  SUBNET_ID={sub.id}")
    return 0


def _create_rds(args) -> int:
    flavor_ref = os.getenv("RDS_FLAVOR_REF", "")
    az = os.getenv("RDS_AZ", "")
    vpc_id = os.getenv("RDS_VPC_ID", "")
    subnet_id = os.getenv("RDS_SUBNET_ID", "")
    password = os.getenv("RDS_PASSWORD", "")
    name = os.getenv("RDS_NAME", "campus-delivery")

    if not all([flavor_ref, az, vpc_id, subnet_id, password]):
        print("缺少参数：RDS_FLAVOR_REF / RDS_AZ / RDS_VPC_ID / RDS_SUBNET_ID / RDS_PASSWORD")
        print("提示：先运行 `probe` 命令查看可用 spec_code（规格码）/VPC/subnet，再把参数写入 .env")
        return 1

    from huaweicloudsdkrds.v3.model import (
        BackupStrategy,
        ChargeInfo,
        CreateInstanceIam5Request,
        CustomerCreateInstanceReq,
        Datastore,
        Ha,
        Volume,
    )

    body = CustomerCreateInstanceReq(
        name=name,
        datastore=Datastore(type="MySQL", version="8.0"),
        ha=Ha(mode="single", replication_mode="sync"),
        flavor_ref=flavor_ref,
        volume=Volume(size=40, type="CLOUDSSD"),
        region=settings.huawei_region,
        availability_zone=az,
        vpc_id=vpc_id,
        subnet_id=subnet_id,
        security_group_id=os.getenv("RDS_SECURITY_GROUP_ID", ""),
        port="3306",
        password=password,
        backup_strategy=BackupStrategy(start_time="03:00-04:00", keep_days=7),
        charge_info=ChargeInfo(charge_mode="postPaid"),
        dry_run=not args.apply,
    )
    req = CreateInstanceIam5Request(x_client_token=str(uuid.uuid4()), body=body)
    resp = huawei.rds_client().create_instance_iam5(req)
    if not args.apply:
        print("(dry_run 检查通过，参数/规格/配额均已校验 OK)")
        print("确认无误后加 --apply 正式创建：python scripts/provision.py create-rds --apply")
        return 0
    inst = resp.instance
    if not inst:
        print("创建请求已提交，但响应中无实例信息，请稍后查询实例列表确认")
        return 0
    print(f"instance_id={inst.id}  name={inst.name}  status={inst.status}")
    print("等待实例 ACTIVE，可执行：python scripts/provision.py wait", inst.id)
    return 0


def _create_dcs(args) -> int:
    spec_code = os.getenv("DCS_SPEC_CODE", "")
    az = os.getenv("DCS_AZ", "")
    vpc_id = os.getenv("DCS_VPC_ID", "")
    subnet_id = os.getenv("DCS_SUBNET_ID", "")
    password = os.getenv("DCS_PASSWORD", "")
    name = os.getenv("DCS_NAME", "campus-delivery-redis")

    if not all([spec_code, az, vpc_id, subnet_id, password]):
        print("缺少参数：DCS_SPEC_CODE / DCS_AZ / DCS_VPC_ID / DCS_SUBNET_ID / DCS_PASSWORD")
        print("提示：先运行 `probe` 命令查看可用 spec_code/VPC/subnet，再把参数写入 .env")
        return 1

    from huaweicloudsdkdcs.v2.model import BssParam, CreateInstanceBody, CreateInstanceRequest

    body = CreateInstanceBody(
        name=name,
        engine="Redis",
        engine_version="5.0",

        capacity=1,
        spec_code=spec_code,
        az_codes=[az],
        vpc_id=vpc_id,
        subnet_id=subnet_id,
        password=password,
        port=6379,
        bss_param=BssParam(charging_mode="postPaid", period_type=2, period_num=1),
    )
    req = CreateInstanceRequest(body=body)
    resp = huawei.dcs_client().create_instance(req)
    insts = resp.instances or []
    if insts:
        for inst in insts:
            print(f"instance_id={inst.instance_id}  name={inst.instance_name}")
        print("等待实例 ACTIVE：python scripts/provision.py wait", insts[0].instance_id)
    else:
        print(f"实例创建请求已提交，响应未返回实例 ID；order_id={resp.order_id}")
        print("请到控制台 DCS 实例列表确认创建进度")
    return 0


def _wait(args) -> int:
    instance_id = args.instance_id
    target = args.target.upper()
    timeout = args.timeout

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            from huaweicloudsdkrds.v3 import ListInstancesRequest

            for inst in huawei.rds_client().list_instances(ListInstancesRequest(id=instance_id)).instances:
                print(f"[RDS] {inst.id} status={inst.status}")
                if inst.status.upper() == target:
                    print(f"内网地址: {inst.data_vip}:{inst.port}")
                    return 0
        except Exception:
            pass

        try:
            from huaweicloudsdkdcs.v2 import ShowInstanceRequest

            inst = huawei.dcs_client().show_instance(ShowInstanceRequest(instance_id=instance_id))
            print(f"[DCS] {inst.instance_id} status={inst.status}")
            if inst.status.upper() == target:
                print(f"内网地址: {inst.ip}:{inst.port}")
                return 0
        except Exception:
            pass

        time.sleep(15)

    print("超时未达到目标状态", target)
    return 2


def main() -> int:
    p = argparse.ArgumentParser(description="校园外卖配送平台 — 华为云资源开通工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_probe = sub.add_parser("probe", help="列出当前账号下可开通资源（VPC/Subnet/RDS Flavor/DCS Flavor）")
    sub_probe.set_defaults(func=_cmd_probe)

    p_sub = sub.add_parser("create-subnet", help="在 VPC 下创建一个子网（参数从 .env 或默认值读取）")
    p_sub.add_argument("--vpc-id", help="VPC ID（缺省自动取列表第一个）")
    p_sub.set_defaults(func=_create_subnet)

    p_crds = sub.add_parser("create-rds", help="创建 RDS MySQL 实例")
    p_crds.add_argument("--apply", action="store_true", help="真正创建（默认 dry_run）")
    p_crds.set_defaults(func=_create_rds)

    p_cdcs = sub.add_parser("create-dcs", help="创建 DCS Redis 实例")
    p_cdcs.add_argument("--apply", action="store_true")
    p_cdcs.set_defaults(func=_create_dcs)

    p_wait = sub.add_parser("wait", help="轮询实例状态到 ACTIVE 并输出连接串")
    p_wait.add_argument("instance_id")
    p_wait.add_argument("--target", default="ACTIVE")
    p_wait.add_argument("--timeout", type=int, default=1800)
    p_wait.set_defaults(func=_wait)


    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())