# Agent Instructions: Azure Architecture Diagram Generation

## Overview
This workspace contains tools to automatically generate Azure architecture diagrams from Infrastructure-as-Code (Terraform, Bicep, ARM templates). The diagrams are created using Python's `diagrams` library, rendered with GraphViz, and converted to editable draw.io format.

---

## Environment Setup

### Python Environment
- **Location**: `C:\Shelly\Youtube\Azure AI\Arch-diag\Arch_Diagrams\venv`
- **Python Version**: 3.13.7
- **Activation**: `.\venv\Scripts\Activate.ps1` (PowerShell)
- **Installation**: See setup instructions below (pygraphviz requires special handling)

### Installed Packages (Exact Versions)
```
diagrams==0.24.4
graphviz==0.20.3
pygraphviz==1.14
graphviz2drawio==1.1.0
puremagic==1.30
svg.path==7.0
```

### Initial Setup from Scratch
```powershell
# 1. Create virtual environment
cd "C:\Shelly\Youtube\Azure AI\Arch-diag\Arch_Diagrams"
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install pygraphviz with GraphViz paths (requires MSVC Build Tools)
$env:GRAPHVIZ_DIR = "C:\Program Files\Graphviz"
pip install --config-settings="--global-option=build_ext" --config-settings="--global-option=-IC:\Program Files\Graphviz\include" --config-settings="--global-option=-LC:\Program Files\Graphviz\lib" pygraphviz

# 3. Install remaining packages
pip install diagrams graphviz graphviz2drawio

# OR use requirements.txt (but pygraphviz needs special install first)
# pip install -r requirements.txt
```

### GraphViz Installation
- **Location**: `C:\Program Files\Graphviz\bin`
- **Version**: 14.0.2
- **Critical**: Must add to PATH before running diagram scripts
  ```powershell
  $env:PATH += ";C:\Program Files\Graphviz\bin"
  ```

### VS Code Extensions
- **Draw.io**: `hediet.vscode-drawio` - For viewing/editing .drawio files
- SVG file association configured for draw.io

---

## File Structure

```
Arch_Diagrams/
├── venv/                           # Python virtual environment
├── requirements.txt                # Python package dependencies
├── diagrams/                       # Output directory for all generated diagrams
│   ├── *.png                       # PNG image outputs
│   ├── *.dot                       # GraphViz DOT source files
│   └── *.drawio                    # Editable draw.io files
├── contoso_architecture.py         # Manual diagram from instructions.md
├── terraform_to_diagram.py         # Terraform parser & diagram generator
├── bicep_lab01_diagram.py          # Bicep lab01 specific generator
├── arm_iis_sql_diagram.py          # ARM template (3-tier IIS+SQL) generator
├── README.md                       # Complete setup & usage documentation
├── script.md                       # YouTube video script (natural reading flow)
└── agent.md                        # THIS FILE - Agent instructions

External Repositories:
├── terraform-demo/                 # Terraform demo with 19 Azure resources
├── avm-bicep-labs/                 # Azure Verified Modules Bicep labs
└── azure-quickstart-templates/     # Azure quickstart ARM/Bicep templates
```

---

## Diagram Generation Workflow

### Complete Process (3 Steps)

#### Step 1: Create Python Diagram Script
- Import required Azure components from `diagrams.azure.*`
- Use proper icon names (e.g., `PublicIpAddresses` not `PublicIPAddresses`)
- Configure graph attributes for layout:
  ```python
  graph_attr = {
      "splines": "ortho",      # Orthogonal lines
      "nodesep": "0.8",        # Node spacing
      "ranksep": "1.2",        # Rank spacing
      "fontsize": "14",
      "bgcolor": "white",
      "pad": "0.5"
  }
  ```
- Use Cluster for logical grouping (VNets, Subnets, Resource Groups)
- Set different background colors for different tiers/clusters
- Set output format: `outformat=["png", "dot"]`

#### Step 2: Run with GraphViz in PATH
```powershell
cd "C:\Shelly\Youtube\Azure AI\Arch-diag\my_azure_diagrams"
.\venv\Scripts\Activate.ps1
$env:PATH += ";C:\Program Files\Graphviz\bin"
python <script_name>.py
```

#### Step 3: Convert DOT to Draw.io
This happens automatically in the script using:
```python
subprocess.run([
    "graphviz2drawio", 
    "diagrams/<name>.dot", 
    "-o", 
    "diagrams/<name>.drawio"
], check=True)
```

---

## Parsing Infrastructure-as-Code

### Terraform Parsing
**File**: `terraform_to_diagram.py`

**Usage**:
```bash
python terraform_to_diagram.py "path/to/main.tf" "project_name"
```

**What it does**:
1. Reads .tf file(s)
2. Uses regex to extract `resource "type" "name"` blocks
3. Detects relationships via:
   - `depends_on` attributes
   - Resource references (e.g., `azurerm_subnet.example.id`)
4. Groups resources by VNet/subnet
5. Generates diagram with connections

**Example**: Successfully parsed `terraform-demo/main.tf` with 19 resources

### Bicep Parsing
**File**: `bicep_lab01_diagram.py` (lab-specific)

**Challenges**:
- Bicep uses module references (harder to parse than Terraform's flat structure)
- Often requires manual inspection of module parameters
- Best approach: Create scenario-specific generators

**Example**: Generated lab01 architecture (CMK with User-Assigned Identity)

### ARM Template Parsing
**File**: `arm_iis_sql_diagram.py`

**Approach**:
- Read ARM template JSON
- Extract resources array
- Map ARM resource types to diagrams icons:
  - `Microsoft.Compute/virtualMachines` → `VM`
  - `Microsoft.Network/loadBalancers` → `LoadBalancers`
  - `Microsoft.Network/virtualNetworks` → `VirtualNetworks`
  - etc.
- Build connections based on `dependsOn` and resource references

**Example**: Generated 3-tier IIS + SQL architecture from `azure-quickstart-templates/demos/iis-2vm-sql-1vm`

---

## Color Coding for Tiers

Use different background colors to distinguish architectural tiers:

```python
# Frontend Tier
frontend_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#E3F2FD",  # Light Blue
    "style": "rounded",
    "margin": "15"
}

# Database Tier
database_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#FFF3E0",  # Light Orange
    "style": "rounded",
    "margin": "15"
}

# Load Balancer
lb_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#F3E5F5",  # Light Purple
    "style": "rounded",
    "margin": "15"
}

# Availability Set
avset_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#E8F5E9",  # Light Green
    "style": "rounded",
    "margin": "15"
}
```

Apply to clusters:
```python
with Cluster("Frontend Subnet", graph_attr=frontend_cluster_attr):
    # components
```

---

## Common Azure Icon Imports

```python
from diagrams import Diagram, Cluster, Edge

# Compute
from diagrams.azure.compute import VM, AvailabilitySets, FunctionApps, ContainerInstances

# Network
from diagrams.azure.network import (
    VirtualNetworks, Subnets, LoadBalancers, 
    ApplicationGateway, FrontDoors, 
    NetworkSecurityGroupsClassic, 
    PublicIpAddresses, NetworkInterfaces,
    PrivateEndpoint, DNSPrivateZones
)

# Database
from diagrams.azure.database import SQLServers, SQLDatabases

# Storage
from diagrams.azure.storage import StorageAccounts, BlobStorage

# Security
from diagrams.azure.security import KeyVaults

# Identity
from diagrams.azure.identity import ManagedIdentities

# Integration
from diagrams.azure.integration import ServiceBus

# Monitoring
from diagrams.azure.analytics import LogAnalyticsWorkspaces
from diagrams.azure.devops import ApplicationInsights
```

**Important**: Always check actual available class names using:
```python
from diagrams.azure import network
print([x for x in dir(network) if not x.startswith('_')])
```

---

## Troubleshooting

### GraphViz Not Found
**Error**: `ExecutableNotFound: failed to execute WindowsPath('dot')`

**Solution**: Add GraphViz to PATH before running:
```powershell
$env:PATH += ";C:\Program Files\Graphviz\bin"
```

### Import Errors
**Error**: `cannot import name 'PublicIPAddresses'`

**Solution**: Check exact class name (case-sensitive):
- Correct: `PublicIpAddresses`
- Wrong: `PublicIPAddresses`

### Cluttered Layout
**Issue**: Auto-generated diagrams have messy layouts

**Solutions**:
1. Adjust graph attributes (`nodesep`, `ranksep`)
2. Use `direction="TB"` or `"LR"`
3. Simplify cluster nesting
4. **Best approach**: Auto-generate, then manually refine in draw.io

---

## Output Files

Each diagram generation produces 3 files:

1. **PNG** - Static image for documentation/presentations
2. **DOT** - GraphViz source (text format, can be version controlled)
3. **DRAWIO** - Editable diagram for manual refinement

**Location**: All files go to `diagrams/` subfolder

**Typical sizes**:
- PNG: ~100-200 KB
- DOT: ~10-15 KB
- DRAWIO: ~120-300 KB

---

## Example Diagrams Created

### 1. Contoso Architecture (Manual)
- **File**: `contoso_architecture.py`
- **Components**: VNet, 3 subnets, Front Door, App Gateway, Web App, Function App, Service Bus, SQL, Storage, Key Vault
- **Output**: `diagrams/contoso_architecture.*`

### 2. Terraform Demo (Auto-parsed)
- **Source**: `terraform-demo/main.tf`
- **Resources**: 19 Azure resources
- **Output**: `diagrams/sc_demo_arch.*`

### 3. Bicep Lab01 (Bicep-parsed)
- **Source**: `avm-bicep-labs/labs/lab01/`
- **Scenario**: CMK with User-Assigned Identity
- **Output**: `diagrams/lab01_architecture.*`

### 4. IIS + SQL 3-Tier (ARM-parsed)
- **Source**: `azure-quickstart-templates/demos/iis-2vm-sql-1vm/azuredeploy.json`
- **Architecture**: Load Balancer → 2 IIS VMs → SQL Server
- **Output**: `diagrams/iis_sql_3tier_arch.*`

---

## Key Principles

1. **Auto-generate first, refine later**: Use Python scripts to get 95% of the diagram, then manually polish in draw.io
2. **Version control DOT files**: They're text-based and show changes clearly
3. **Color code tiers**: Makes diagrams easier to understand at a glance
4. **Use clusters liberally**: Group related resources (VNets, Subnets, Resource Groups)
5. **Edge labels**: Label connections with protocols/ports for clarity
6. **Always add GraphViz to PATH**: Critical step before running any script

---
