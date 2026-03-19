# Subnets are defined in vpc.tf via the VPC module.
# This file documents the subnet design for educational purposes.

# ┌──────────────────────────────────────────────────────┐
# │                    VPC: 10.0.0.0/16                  │
# │                                                      │
# │  ┌────────────────┐    ┌────────────────┐            │
# │  │ Public Subnet  │    │ Public Subnet  │            │
# │  │ us-east-1a     │    │ us-east-1b     │            │
# │  │ 10.0.101.0/24  │    │ 10.0.102.0/24  │            │
# │  │ (NAT GW, ALB)  │    │ (ALB)          │            │
# │  └────────────────┘    └────────────────┘            │
# │                                                      │
# │  ┌────────────────┐    ┌────────────────┐            │
# │  │ Private Subnet │    │ Private Subnet │            │
# │  │ us-east-1a     │    │ us-east-1b     │            │
# │  │ 10.0.1.0/24    │    │ 10.0.2.0/24    │            │
# │  │ (EKS Nodes)    │    │ (EKS Nodes)    │            │
# │  └────────────────┘    └────────────────┘            │
# │                                                      │
# └──────────────────────────────────────────────────────┘
#
# LEARNING NOTES:
# - Public subnets have internet access via Internet Gateway.
# - Private subnets access internet via NAT Gateway (for pulling images, etc).
# - EKS nodes run in private subnets for security.
# - Load balancers are placed in public subnets.
