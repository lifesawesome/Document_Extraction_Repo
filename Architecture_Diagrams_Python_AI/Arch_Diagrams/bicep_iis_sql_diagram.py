"""
Azure Architecture Diagram Generator for IIS + SQL 3-Tier Demo
Based on bicep-demo/demos/iis-2vm-sql-1vm/main.bicep

Architecture Components:
- Virtual Network with 2 subnets (Frontend & Database)
- Load Balancer with 2 IIS Web Server VMs in Availability Set
- SQL Server 2022 VM in backend subnet
- Network Security Groups for each tier
- Public IPs for Load Balancer and SQL Server

Generates PNG, DOT, and Draw.io format diagrams
"""

import subprocess
from diagrams import Diagram, Cluster, Edge
from diagrams.azure.compute import VM, AvailabilitySets
from diagrams.azure.network import (
    VirtualNetworks, LoadBalancers, PublicIpAddresses,
    NetworkSecurityGroupsClassic, NetworkInterfaces, Subnets
)
from diagrams.onprem.client import Users

# Graph attributes for clean layout
graph_attr = {
    "splines": "ortho",
    "nodesep": "1.0",
    "ranksep": "1.5",
    "fontsize": "14",
    "bgcolor": "white",
    "pad": "0.5",
    "compound": "true"
}

# Cluster attributes for different tiers
vnet_cluster_attr = {
    "fontsize": "14",
    "bgcolor": "#E8F4F8",
    "style": "dashed",
    "margin": "25",
    "labelloc": "t"
}

frontend_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#E3F2FD",
    "style": "rounded",
    "margin": "20",
    "labelloc": "t"
}

database_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#FFF3E0",
    "style": "rounded",
    "margin": "20",
    "labelloc": "t"
}

lb_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#F3E5F5",
    "style": "rounded",
    "margin": "15",
    "labelloc": "t"
}

avset_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#E8F5E9",
    "style": "rounded",
    "margin": "15",
    "labelloc": "t"
}

# Create the diagram
with Diagram(
    "IIS + SQL Server 3-Tier Architecture (Bicep Demo)",
    filename="diagrams/bicep_iis_sql_3tier",
    outformat=["png", "dot"],
    show=False,
    direction="TB",
    graph_attr=graph_attr
):
    
    # External users
    users = Users("Internet Users")
    
    # Public IP for Load Balancer
    web_public_ip = PublicIpAddresses("cust1websrvpip\n(Web LB Public IP)\nDNS: cust1websrvlb")
    
    # VNet container with all internal resources
    with Cluster("cust1Vnet\n(10.0.0.0/16)", graph_attr=vnet_cluster_attr):
        
        # Load Balancer (logical placement at VNet level)
        with Cluster("Load Balancer", graph_attr=lb_cluster_attr):
            web_lb = LoadBalancers("cust1webSrvlb\n(Load Balancer)\nPort 80")
        
        # Frontend Subnet
        with Cluster("FESubnetName\n(10.0.0.0/24)", graph_attr=frontend_cluster_attr):
            nsg_frontend = NetworkSecurityGroupsClassic("feNsg\n(Allow HTTP 80)")
            
            # Availability Set with Web Servers
            with Cluster("Availability Set", graph_attr=avset_cluster_attr):
                avset = AvailabilitySets("cust1webSrvAS\n(2 Fault/20 Update Domains)")
                web_vm1 = VM("cust1webSrv0\nWindows Server 2022\nIIS Web Server\nD2s_v3")
                web_vm2 = VM("cust1webSrv1\nWindows Server 2022\nIIS Web Server\nD2s_v3")
                web_nic1 = NetworkInterfaces("NIC0")
                web_nic2 = NetworkInterfaces("NIC1")
        
        # Database Subnet
        with Cluster("DBSubnetName\n(10.0.2.0/24)", graph_attr=database_cluster_attr):
            nsg_db = NetworkSecurityGroupsClassic("dbNsg\n(Allow SQL 1433)\n(Block Internet)")
            sql_vm = VM("cust1sqlSrv14\nSQL Server 2022\nStandard Edition\nD4s_v3")
            sql_nic = NetworkInterfaces("sqlSrvNIC")
            sql_public_ip = PublicIpAddresses("SqlPIP\n(Management)")
    
    # Connection flows - User to Web Tier
    users >> Edge(label="HTTPS/HTTP", color="blue") >> web_public_ip
    web_public_ip >> Edge(label="", color="blue") >> web_lb
    
    # Load Balancer to Web Servers
    web_lb >> Edge(label="Port 80\n(Backend Pool)", color="blue") >> web_nic1
    web_lb >> Edge(label="Port 80\n(Backend Pool)", color="blue") >> web_nic2
    
    # NICs to VMs
    web_nic1 >> Edge(label="", color="darkblue") >> web_vm1
    web_nic2 >> Edge(label="", color="darkblue") >> web_vm2
    
    # Availability Set relationship
    web_vm1 >> Edge(label="Member", style="dotted", color="green") >> avset
    web_vm2 >> Edge(label="Member", style="dotted", color="green") >> avset
    
    # Web servers to SQL Server
    web_vm1 >> Edge(label="SQL:1433", color="orange") >> sql_vm
    web_vm2 >> Edge(label="SQL:1433", color="orange") >> sql_vm
    
    # SQL NIC to SQL VM
    sql_nic >> Edge(label="", color="darkorange") >> sql_vm
    
    # SQL Public IP (for management)
    sql_public_ip >> Edge(label="RDP/Management", style="dashed", color="gray") >> sql_nic
    
    # NSG associations
    nsg_frontend >> Edge(label="Protects", style="dotted", color="red") >> web_nic1
    nsg_db >> Edge(label="Protects", style="dotted", color="red") >> sql_nic

print("✓ PNG and DOT files generated in diagrams/")

# Convert DOT to Draw.io format
try:
    subprocess.run([
        "graphviz2drawio", 
        "diagrams/bicep_iis_sql_3tier.dot", 
        "-o", 
        "diagrams/bicep_iis_sql_3tier.drawio"
    ], check=True)
    print("✓ Draw.io file generated: diagrams/bicep_iis_sql_3tier.drawio")
except subprocess.CalledProcessError as e:
    print(f"✗ Failed to convert to Draw.io format: {e}")
except FileNotFoundError:
    print("✗ graphviz2drawio not found. Install with: pip install graphviz2drawio")

print("\n" + "="*60)
print("BICEP DEMO ARCHITECTURE SUMMARY")
print("="*60)
print("\nArchitecture Overview:")
print("  - 3-Tier Web Application (IIS + SQL Server)")
print("  - Resource Group Scoped Deployment")
print("\nNetworking:")
print("  - VNet: cust1Vnet (10.0.0.0/16)")
print("  - Frontend Subnet: 10.0.0.0/24")
print("  - Database Subnet: 10.0.2.0/24")
print("  - NSG Rules: HTTP(80) allowed to frontend, SQL(1433) from frontend to DB")
print("\nWeb Tier:")
print("  - Load Balancer: cust1webSrvlb with public IP")
print("  - Availability Set: 2 fault domains, 20 update domains")
print("  - 2x IIS VMs: Windows Server 2022 (Standard_D2s_v3)")
print("  - Health Probe: TCP port 80")
print("\nDatabase Tier:")
print("  - 1x SQL Server 2022 Standard VM (Standard_D4s_v3)")
print("  - Managed Disks: Premium_LRS")
print("  - Public IP for management access")
print("  - Outbound internet traffic blocked")
print("\nSecurity:")
print("  - Frontend NSG: Allows HTTP/80 from Internet")
print("  - Database NSG: Allows SQL/1433 from Frontend only")
print("  - Database NSG: Blocks all internet outbound")
print("\nGenerated files:")
print("  - diagrams/bicep_iis_sql_3tier.png")
print("  - diagrams/bicep_iis_sql_3tier.dot")
print("  - diagrams/bicep_iis_sql_3tier.drawio")
print("="*60)
