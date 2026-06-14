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
  }

  # Uncomment after creating S3 bucket for remote state
  # backend "s3" {
  #   bucket = "otel-lab-tfstate-suritm7543"
  #   key    = "eks/terraform.tfstate"
  #   region = "us-east-2"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "otel-observability-lab"
      Owner       = "suritm7543"
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

# ── DATA SOURCES ──────────────────────────────────────────────────────────────

data "aws_availability_zones" "available" {
  state = "available"
}

# ── VPC ───────────────────────────────────────────────────────────────────────
# VPC module v6.6.1 — verified latest as of June 2026

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.6"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway     = true
  single_nat_gateway     = true   # cost optimisation for lab; use one per AZ in prod
  enable_dns_hostnames   = true
  enable_dns_support     = true

  # Required tags for EKS load balancer controller to discover subnets
  public_subnet_tags = {
    "kubernetes.io/role/elb"                    = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"           = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

# ── EKS CLUSTER ───────────────────────────────────────────────────────────────
# EKS module v21.x — required for AWS provider 6.x compatibility
#
# CRITICAL: vpc_cni is NOT in cluster_addons.
# Cilium replaces the VPC CNI in ENI mode. Installing both causes split-brain.
# The aws-node DaemonSet will be deleted after Cilium is installed (see null_resource below).

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.cluster_name
  kubernetes_version = "1.35"   # argument renamed from cluster_version in v21

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  endpoint_public_access = true

  # v21 uses access entries instead of aws-auth ConfigMap
  enable_cluster_creator_admin_permissions = true

  # CRITICAL: Keep node groups EMPTY here.
  # We create the node group as a separate resource below so we can enforce
  # depends_on = [helm_release.cilium] — the #1 EKS+Cilium failure mode prevention.
  eks_managed_node_groups = {}

  # Only install addons that don't conflict with Cilium
  # vpc-cni is intentionally excluded — Cilium is the CNI in ENI mode
  addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
  }
}

# ── IAM ROLE FOR NODE GROUP ───────────────────────────────────────────────────

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

# ── CILIUM — MUST INSTALL BEFORE NODE GROUP JOINS ─────────────────────────────
# This is the single most critical sequencing constraint in the project.
# Cilium must be present when nodes first join so they initialise with the
# correct CNI. Installing Cilium after nodes join = split-brain CNI state.

resource "helm_release" "cilium" {
  name       = "cilium"
  repository = "https://helm.cilium.io"
  chart      = "cilium"
  version    = "1.19.4"
  namespace  = "kube-system"
  create_namespace = false

  wait    = true
  timeout = 600   # 10 minutes — Cilium can take a few minutes to be fully ready

  values = [file("${path.module}/../../helm/cilium-values.yaml")]

  # Cluster must exist, but NO nodes yet
  depends_on = [module.eks]
}

# ── DELETE aws-node DaemonSet AFTER CILIUM INSTALLS ──────────────────────────
# In ENI mode, Cilium fully replaces the AWS VPC CNI.
# The aws-node DaemonSet conflicts with Cilium's ENI management.
# Must be removed AFTER Cilium is running, BEFORE nodes join.

resource "null_resource" "delete_aws_node" {
  triggers = {
    cluster_name = module.eks.cluster_name
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}
      kubectl -n kube-system delete daemonset aws-node --ignore-not-found=true
    EOT
  }

  depends_on = [helm_release.cilium]
}

# ── EKS NODE GROUP — AFTER CILIUM AND aws-node DELETION ──────────────────────
# CRITICAL: depends_on both Cilium AND the aws-node deletion.
# Nodes join AFTER Cilium is ready and aws-node is gone.
#
# CRITICAL: The node taint node.cilium.io/agent-not-ready=true:NoExecute
# is REQUIRED by Cilium 1.19 docs. It prevents app pods from scheduling
# before Cilium has fully initialised networking on the node.
# Cilium automatically removes this taint once it is ready on each node.

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

  # AL2023 ships Linux kernel 6.1 — fully compatible with Cilium 1.19.4 eBPF
  ami_type = "AL2023_x86_64_STANDARD"

  # REQUIRED by Cilium 1.19 docs for EKS managed node groups
  # Cilium removes this taint automatically once it is ready on the node
  taint {
    key    = "node.cilium.io/agent-not-ready"
    value  = "true"
    effect = "NO_EXECUTE"
  }

  labels = {
    role = "main"
  }

  depends_on = [
    null_resource.delete_aws_node,
    aws_iam_role_policy_attachment.node_group_policies,
  ]
}

# ── NAMESPACES ────────────────────────────────────────────────────────────────

resource "kubernetes_namespace" "observability" {
  metadata {
    name = "observability"
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
  depends_on = [aws_eks_node_group.main]
}

resource "kubernetes_namespace" "otel_lab" {
  metadata {
    name = "otel-lab"
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
  depends_on = [aws_eks_node_group.main]
}
