terraform {
  required_version = ">= 1.15.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.50.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.36.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "otel-observability-lab"
      Owner       = "suritmaharana-maker"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args = [
        "eks", "get-token",
        "--cluster-name", module.eks.cluster_name,
        "--region", var.aws_region
      ]
    }
  }
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = [
      "eks", "get-token",
      "--cluster-name", module.eks.cluster_name,
      "--region", var.aws_region
    ]
  }
}

# â”€â”€ DATA SOURCES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

data "aws_availability_zones" "available" {
  state = "available"
}

# â”€â”€ VPC â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.6"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway   = true
  single_nat_gateway   = true
  enable_dns_hostnames = true
  enable_dns_support   = true

  public_subnet_tags = {
    "kubernetes.io/role/elb"                    = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"           = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

# â”€â”€ EKS CLUSTER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CRITICAL: addons block is intentionally EMPTY.
#
# Reason: The EKS module v21 waits for addons to reach ACTIVE state immediately
# after cluster creation â€” before any nodes exist. CoreDNS requires nodes to
# schedule on. With Cilium replacing the VPC CNI there is no Fargate fallback.
# Result: 20-minute timeout then failure. This was the root cause of the first
# failed apply.
#
# Fix: CoreDNS and kube-proxy are installed as standalone aws_eks_addon resources
# below, with explicit depends_on = [aws_eks_node_group.main]. This guarantees
# nodes exist before addons are installed.
# Source: github.com/terraform-aws-modules/terraform-aws-eks issue #2585
#         hackmd.io/@eCHO-live/138 (confirmed working pattern)

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.cluster_name
  kubernetes_version = "1.35"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  endpoint_public_access = true

  enable_cluster_creator_admin_permissions = true

  # Node groups managed outside this module â€” see aws_eks_node_group below
  eks_managed_node_groups = {}

  # INTENTIONALLY EMPTY â€” addons installed after nodes join
  # See standalone aws_eks_addon resources below
  addons = {}
}

# â”€â”€ IAM ROLE FOR NODE GROUP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

resource "aws_iam_role" "node_group" {
  name = "${var.cluster_name}-node-group-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "node_group_policies" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
  ])
  role       = aws_iam_role.node_group.name
  policy_arn = each.value
}

# â”€â”€ PATCH aws-node BEFORE CILIUM â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Source: docs.cilium.io/en/stable + egrosdou01.github.io/personal-blog
#
# Patching aws-node with a node selector that no node will ever match
# effectively disables it without deleting it. This is safer than deletion:
# - Idempotent: can be run multiple times without error
# - Reversible: can be re-enabled by removing the node selector
# - Official Cilium recommendation for ENI mode on EKS
#
# Must run BEFORE Cilium installs so ENI management does not conflict.

resource "null_resource" "patch_aws_node" {
  triggers = {
    cluster_name = module.eks.cluster_name
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}
      kubectl -n kube-system patch daemonset aws-node \
        --type='strategic' \
        -p='{"spec":{"template":{"spec":{"nodeSelector":{"io.cilium/aws-node-enabled":"true"}}}}}'
    EOT
  }

  depends_on = [module.eks]
}

# â”€â”€ CILIUM â€” INSTALLS BEFORE NODE GROUP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Must depend on patch_aws_node so aws-node is disabled before Cilium starts
# managing ENIs. Node group depends on this resource â€” enforcing correct order.

resource "helm_release" "cilium" {
  name             = "cilium"
  repository       = "https://helm.cilium.io"
  chart            = "cilium"
  version          = "1.19.4"
  namespace        = "kube-system"
  create_namespace = false

  wait    = true
  timeout = 600

  values = [file("${path.module}/../../helm/cilium-values.yaml")]

  depends_on = [null_resource.patch_aws_node]
}

# â”€â”€ EKS NODE GROUP â€” AFTER CILIUM â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Nodes join AFTER Cilium is ready. Cilium removes the agent-not-ready taint
# automatically once it has initialised on each node.

resource "aws_eks_node_group" "main" {
  cluster_name    = module.eks.cluster_name
  node_group_name = "${var.cluster_name}-main"
  node_role_arn   = aws_iam_role.node_group.arn
  subnet_ids      = module.vpc.private_subnets

  instance_types = [var.node_instance_type]

  scaling_config {
    desired_size = var.node_count
    min_size     = 1
    max_size     = 6
  }

  update_config {
    max_unavailable = 1
  }

  # AL2023 ships Linux kernel 6.1 â€” fully compatible with Cilium 1.19.4 eBPF
  ami_type = "AL2023_x86_64_STANDARD"

  # Required by Cilium 1.19 docs for EKS managed node groups
  # Cilium removes this taint automatically once ready on each node
  taint {
    key    = "node.cilium.io/agent-not-ready"
    value  = "true"
    effect = "NO_EXECUTE"
  }

  labels = {
    role = "main"
  }

  depends_on = [
    helm_release.cilium,
    aws_iam_role_policy_attachment.node_group_policies,
  ]
}

# â”€â”€ COREDNS ADDON â€” AFTER NODES JOIN â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CRITICAL: depends_on = [aws_eks_node_group.main]
# This is the fix for the CoreDNS DEGRADED timeout failure.
# CoreDNS requires nodes to schedule on. Installing it before nodes exist
# causes a 20-minute timeout then failure.
# Source: github.com/terraform-aws-modules/terraform-aws-eks/issues/2585

resource "aws_eks_addon" "coredns" {
  cluster_name                = module.eks.cluster_name
  addon_name                  = "coredns"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.main]
}

# â”€â”€ KUBE-PROXY ADDON â€” AFTER NODES JOIN â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

resource "aws_eks_addon" "kube_proxy" {
  cluster_name                = module.eks.cluster_name
  addon_name                  = "kube-proxy"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.main]
}

# â”€â”€ NAMESPACES â€” AFTER NODES AND ADDONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

resource "kubernetes_namespace" "observability" {
  metadata {
    name = "observability"
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
  depends_on = [
    aws_eks_addon.coredns,
    aws_eks_addon.kube_proxy,
  ]
}

resource "kubernetes_namespace" "otel_lab" {
  metadata {
    name = "otel-lab"
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
  depends_on = [
    aws_eks_addon.coredns,
    aws_eks_addon.kube_proxy,
  ]
}
