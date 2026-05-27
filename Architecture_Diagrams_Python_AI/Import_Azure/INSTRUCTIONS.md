# Agent Instructions: Azure Network Flow Diagram Generation

You are tasked with generating a professional network flow diagram from an Azure infrastructure JSON export. Follow these instructions precisely.

---

## Output Script

Create the diagram generator script named: `generate_network_flow_diagram.py`

---

## Required Libraries & Tools

### Python Library: `diagrams` (mingrammer/diagrams)

Use the **`diagrams`** library (pip install diagrams) for diagram generation. This provides real Azure service icons and a clean cluster/node API.

Key imports and their purposes:
- `from diagrams import Diagram, Cluster, Edge` — Core diagram, grouping, and arrow objects
- `from diagrams.azure.compute import VM, VMScaleSet` — Compute icons
- `from diagrams.azure.network import VirtualNetworks, Subnets, LoadBalancers, PublicIpAddresses, Firewall, VirtualNetworkGateways, PrivateEndpoint` — Network icons
- `from diagrams.azure.database import SQLServers` — Database icons
- `from diagrams.azure.security import KeyVaults` — Security icons
- `from diagrams.azure.storage import StorageAccounts` — Storage icons
- `from diagrams.onprem.network import Internet` — Internet/external user icon

### GraphViz (System Dependency)

GraphViz must be installed on the system (the `diagrams` library requires it).  
On Windows it may not be on PATH — check common install locations:
- `C:\Program Files\Graphviz\bin\dot.exe`
- `C:\Program Files (x86)\Graphviz\bin\dot.exe`
- `C:\ProgramData\chocolatey\bin\dot.exe`

Use `shutil.which('dot')` first, then fall back to these paths if not found.

### DrawIO Conversion: `graphviz2drawio`

Use the `graphviz2drawio` tool (pip install graphviz2drawio) to convert the DOT output to a `.drawio` file. Wrap the call in a try/except so it degrades gracefully if the tool is not available.

---

## Input

You will receive an `azure-infrastructure.json` file containing exported Azure resources organized by subscriptions, resource groups, and resource types. The JSON structure uses **snake_case** keys (e.g., `address_space`, `ip_configurations`, `virtual_network_peerings`) with no `properties` wrapper — all fields are at the top level of each object.

### JSON Traversal Pattern

For every subscription → resource group → resources:
- Network resources are under `resources.network` (virtualNetworks, loadBalancers, networkInterfaces, privateEndpoints, firewalls, etc.)
- Compute resources are under `resources.compute` (virtualMachines, virtualMachineScaleSets)
- SQL resources are under `resources.sql` (servers, databases)
- Key Vault resources are under `resources.keyvault` (vaults)
- Storage resources are under `resources.storage` (storageAccounts)

When storing VNet data in internal maps, carry along the related resource categories (compute, network, sql, keyvault) from the same resource group so they can be rendered inside the correct VNet cluster.

---

## Script Architecture

### Class: `AzureNetworkDiagramGenerator`

The script should use a single class with this lifecycle:

1. **`load_infrastructure()`** — Load JSON file
2. **`analyze_topology()`** — Build lookup maps, detect hub/spoke, collect peerings
3. **`generate_diagram()`** — Render the diagram using the `diagrams` library
4. **`run()`** — Orchestrate the above steps

### Internal State (Instance Variables)

Maintain these lookup dictionaries/sets during analysis:
- **`vnet_map`** — VNet ID → full VNet data (including related RG resources)
- **`subnet_map`** — Subnet ID → subnet data (with parent VNet ID)
- **`nic_subnet_map`** — NIC ID → Subnet ID (built from NIC ip_configurations)
- **`resource_subnet_map`** — Resource ID → Subnet ID (for VMs, VMSS, LBs)
- **`hub_vnets`** / **`spoke_vnets`** — Sets of VNet IDs classified as hub or spoke
- **`peerings`** — List of peering records (source, target, state)
- **`private_endpoints`** — List of PE records (id, name, subnet_id, connections)
- **`nodes`** — Resource ID → diagram node object (for drawing edges later)
- **`vnet_nodes`** — VNet ID → representative diagram node (for peering edges)
- **`drawn_peerings`** — Set of sorted VNet ID tuples (to avoid duplicate peering edges)

### Tracking Lists for Traffic Flows

During rendering, collect these lists to draw traffic flows **after** all nodes exist:
- **`external_lbs`** — LB nodes that have a public IP (for Internet → LB edges)
- **`hub_fw_nodes`** — Firewall/NVA VM nodes in hub VNet (for routed traffic edges)
- **`spoke_lbs`** — Internal LB nodes in spoke VNets (targets for routed traffic)

---

## Diagram Layout

### Hierarchy (Top to Bottom)

The diagram must follow a strict top-down hierarchy:

1. **Internet/External Users** — Always at the very top, inside an "External" cluster
2. **Hub Network Layer** — VNets identified as hubs (contain firewalls, gateways, or "hub" in name)
3. **Spoke Network Layer** — All other VNets that peer with the hub
4. **Each VNet contains** — Resource Groups → VNet cluster → Subnets → Resources

### Hub-Spoke Detection

Identify a VNet as **Hub** if any of these conditions are true:
- VNet name contains "hub" (case-insensitive)
- Contains a subnet with "firewall", "gateway", or "azurefirewall" in the name
- Contains an Azure Firewall resource
- Contains a VPN or ExpressRoute Gateway

All other VNets connected to a hub via peering are **Spokes**.

### Resource Placement

- Resources must be placed **inside their correct subnet** based on NIC or IP configuration mappings
- SQL Servers, Key Vaults, and Storage Accounts belong **inside their VNet cluster** (not inside a specific subnet, but within the VNet grouping)
- Private Endpoints must be shown in their subnet with connections to target resources
- Do NOT show NSGs as separate icons — they clutter the diagram

### VNet Rendering Structure

Each VNet should be rendered with this nesting:
```
Subscription Cluster
  └── Resource Group Cluster
        └── VNet Cluster (show name + CIDR, labeled HUB or SPOKE)
              ├── Subnet Cluster 1 (show name + CIDR)
              │     ├── VMs / VMSS / LBs / Private Endpoints
              ├── Subnet Cluster 2
              │     ├── ...
              ├── SQL Servers (inside VNet, outside subnets)
              └── Key Vaults (inside VNet, outside subnets)
```

### Representative Nodes for Peering Edges

Since the `diagrams` library draws edges between **nodes** (not clusters), each VNet needs a **representative node** for peering arrows. Use the first resource node rendered inside the VNet. If a VNet has no resources, create a `VirtualNetworks` placeholder node.

---

## Traffic Flows

**Important**: Draw all traffic flow edges **after** all nodes have been rendered (inside the `Diagram` context but after all clusters). This ensures all node references exist.

### North-South Traffic (External ↔ Internal)

Show arrows from Internet to Azure resources:
- **Internet → External Load Balancers**: Green bold arrow labeled "HTTPS" (penwidth 2) for any LB with a public IP
- **Internet → Application Gateway**: Green bold arrow if App Gateway exists
- **Internet → VPN/ER Gateway**: Purple dashed arrow labeled "VPN" or "ExpressRoute"

Limit to a reasonable number of arrows (e.g., max 4 external LBs) to avoid clutter.

### East-West Traffic (Internal ↔ Internal)

- **VNet Peering**: Blue bidirectional arrows (`dir="both"`) between peered VNets using representative nodes, labeled with peering state. Use bold style for hub-spoke peerings, dashed for spoke-spoke. Use a `drawn_peerings` set with sorted VNet ID tuples to avoid drawing duplicate peering edges.
- **Hub → Spoke routing**: Blue dashed arrows from hub firewall/NVA node to spoke internal LB nodes, labeled "Routed Traffic" (penwidth 1.5)
- **Load Balancer → Backend**: Blue arrows from LB to backend VMSS or VMs labeled "Backend". Match backends by checking if the VMSS ID appears in the `backend_ip_configurations[].id` string of the LB's backend address pools.

### Data Access Flows

- **Private Endpoint → Target**: Orange bold arrows from PE nodes to target SQL/KeyVault/Storage nodes, labeled "Private Link". Target ID comes from `private_link_service_connections[].private_link_service_id`.

---

## Visual Design

### Diagram Configuration (graph_attr)

Use these GraphViz attributes on the `Diagram` object:
- `splines: ortho` — Orthogonal (right-angle) line routing
- `nodesep: 0.8` — Horizontal spacing between nodes
- `ranksep: 1.2` — Vertical spacing between ranks
- `fontname: Segoe UI` — Professional font
- `bgcolor: white` — White background
- `pad: 0.8` — Padding around the diagram
- `compound: true` — Allow edges between clusters
- `rankdir: TB` — Top-to-bottom layout

Node and edge attributes: `fontsize: 10`, `fontname: Segoe UI` for nodes; `fontsize: 9` for edges.

### Color Scheme (Professional/Muted)

Use subtle, professional colors for all containers — avoid bright/saturated colors. Let Azure service icons provide the color distinction.

| Element | Color | Hex |
|---------|-------|-----|
| Hub VNet container | Light gray | `#E8E8E8` |
| Spoke VNet container | Very light gray | `#F5F5F5` |
| Subscription container | Near white | `#FAFAFA` |
| Resource Group container | White | `#FFFFFF` |
| Firewall subnet | Slightly darker gray | `#E0E0E0` |
| Web/App/Data/PE subnets | Light gray | `#F0F0F0` |
| Internet container | Light gray | `#E8E8E8` |
| Default/other subnets | White | `#FFFFFF` |

### Subnet Color by Purpose

Color subnet backgrounds based on name keywords:
- "firewall" or "fw" → Firewall color (`#E0E0E0`)
- "web" or "ingress" → Web color (`#F0F0F0`)
- "app" → App color (`#F0F0F0`)
- "data" → Data color (`#F0F0F0`)
- "pe" or "endpoint" → PE color (`#F0F0F0`)
- Everything else → White (`#FFFFFF`)

### Arrow Colors and Styles

| Traffic Type | Color | Style | Label |
|-------------|-------|-------|-------|
| Internet → External LB | `green` | bold, penwidth 2 | "HTTPS" |
| Hub FW → Spoke LB | `blue` | dashed, penwidth 1.5 | "Routed Traffic" |
| VNet Peering (hub-spoke) | `blue` | bold, penwidth 2, bidirectional | "VNet Peering\n{state}" |
| VNet Peering (spoke-spoke) | `blue` | dashed, penwidth 2, bidirectional | "VNet Peering\n{state}" |
| LB → Backend VMSS/VM | `blue` | default | "Backend" |
| Private Endpoint → Target | `orange` | bold | "Private Link" |
| VPN/ExpressRoute | `purple` | dashed | "VPN" or "ExpressRoute" |

### Labels

- Every arrow must have a label describing the traffic type
- VNet clusters must show name and CIDR range
- Subnet clusters must show name and CIDR
- Resources should show name and key attribute (e.g., VM size, VMSS capacity `x{count}`)
- External LBs should be labeled with 🌐 emoji and "(External)"
- Firewall/NVA VMs should be labeled with 🔥 emoji and "(NVA)"
- Hub VNets labeled with 🏢 HUB prefix, Spokes with 🌐 SPOKE prefix
- Subscription clusters prefixed with ☁️ emoji
- Resource Group clusters prefixed with 📂 emoji

### Cluster Style

All clusters use `style: rounded` and appropriate `margin` values:
- Subscription: margin 20
- Resource Group: margin 15
- VNet: margin 15
- Subnet: margin 10

---

## Resource Mapping Logic

### NIC → Subnet Pre-indexing

**First pass**: Before mapping resources, iterate all NICs across all resource groups and build a `nic_id → subnet_id` map from `ip_configurations[0].subnet.id`. This map is essential for VM placement since VMs reference NICs, not subnets directly.

### Finding Resource Subnets

To determine which subnet a resource belongs to:

1. **VMs**: Trace `network_profile.network_interfaces[].id` → look up in NIC-subnet map
2. **VMSS**: Get `virtual_machine_profile.network_profile.network_interface_configurations[0].ip_configurations[0].subnet.id`
3. **Load Balancers**: Get `frontend_ip_configurations[0].subnet.id` (internal) or check for `public_ip_address` (external). External LBs may not have a subnet — place them in a subnet if one exists, otherwise in the VNet cluster.
4. **Private Endpoints**: Get `subnet.id` directly from the PE object
5. **Firewalls/Gateways**: Get `ip_configurations[0].subnet.id`

### Identifying External vs Internal Load Balancers

- **External**: Has `frontend_ip_configurations[].public_ip_address.id` (non-empty) — receives Internet traffic
- **Internal**: Has `frontend_ip_configurations[].subnet.id` only — internal traffic

### Firewall/NVA VM Detection

If a VM's name contains "fw" or "firewall" (case-insensitive), treat it as a network virtual appliance (NVA) that routes traffic. Track these nodes separately for hub→spoke routed traffic edges.

### VNet Peering Information

Found at `vnet.virtual_network_peerings[]`:
- `remote_virtual_network.id` — the peered VNet
- `peering_state` — Connected, Disconnected, etc.
- `allow_forwarded_traffic` — indicates hub routing
- `allow_gateway_transit` — indicates gateway sharing

### LB → Backend Pool Matching

To draw LB → backend edges: iterate `lb.backend_address_pools[].backend_ip_configurations[]` and check if the configuration ID string **contains** a known VMSS resource ID. If so, draw an edge from the LB node to the VMSS node.

---

## What NOT to Include

- Do NOT show NSGs as icons (too much clutter)
- Do NOT show NICs separately (implied by VM placement)
- Do NOT show Disks
- Do NOT show Network Watchers
- Do NOT create a separate "Data Tier" outside subscriptions — keep resources in their RG/VNet
- Do NOT show empty resource groups
- Do NOT show empty subnets without any resources — use a simple `Subnets` placeholder node if a subnet has no mapped resources (so cluster isn't empty)

---

## Output Requirements

### Output Directory

Create a `diagrams/` subdirectory for all output files.

### Output Files

Generate three output files:
1. **PNG** — Static preview image (generated directly by the `diagrams` library using `outformat=["png", "dot"]`)
2. **DOT** — GraphViz source for version control (generated alongside PNG)
3. **DRAWIO** — Editable diagram (converted from DOT using `graphviz2drawio`). Wrap conversion in try/except since the tool may not be installed.

The draw.io file must be editable so users can refine layout, add annotations, and export to other formats.

---

## CLI Interface

The script should accept:
- **Positional argument**: Input JSON file path (required)
- **`-o` / `--output`**: Output filename prefix (default: `network_flow_diagram`)

Validate that the input file exists before proceeding. Exit with error code 1 if not found.

---

## Handling Dynamic Resources

The JSON export may contain varying resources over time. The diagram generator must:

- Dynamically discover all resource types present in the JSON
- Only show resources that exist (don't hardcode expectations)
- Handle missing optional fields gracefully (use `.get()` with defaults everywhere)
- Scale layout based on number of resources
- Group related resources logically even if new types are added
- Use a `nodes` dictionary to track all rendered resource nodes by ID for drawing edges later

---

## Error Handling & Robustness

- Always use `.get()` with default values when accessing JSON fields
- Wrap `graphviz2drawio` conversion in try/except
- Check file existence before loading
- Print clear status messages with emoji indicators (📂, 🔍, 🎨, ✅, ⚠️, ❌) for each stage
- Print a summary at the end: total resources rendered, output file paths

---

## Summary

Create a clean, professional network flow diagram that:
1. Uses the `diagrams` (mingrammer) Python library with real Azure icons
2. Shows clear top-down hierarchy (Internet → Hub → Spokes)
3. Places all resources in their correct network location using NIC→subnet mapping
4. Visualizes traffic flows with labeled, colored arrows drawn after all nodes exist
5. Uses muted gray colors for containers, letting Azure service icons provide distinction
6. Outputs PNG + DOT directly, and converts to DrawIO via `graphviz2drawio`
7. Handles dynamic/variable infrastructure gracefully
