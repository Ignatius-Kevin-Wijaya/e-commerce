# Security groups are managed by the EKS module.
# This file documents the security group design.

# LEARNING NOTES:
# - EKS module automatically creates security groups for:
#   1. Cluster control plane → node communication
#   2. Node → node communication (pod-to-pod)
#   3. Node → control plane (kubelet API)
#
# Additional security groups can be added here if needed:
# - RDS access from specific pods
# - External API access
# - Bastion host access

# Example: Allow EKS nodes to access RDS
# resource "aws_security_group" "rds_from_eks" {
#   name_prefix = "rds-from-eks-"
#   vpc_id      = module.vpc.vpc_id
#
#   ingress {
#     from_port       = 5432
#     to_port         = 5432
#     protocol        = "tcp"
#     security_groups = [module.eks.node_security_group_id]
#   }
# }
