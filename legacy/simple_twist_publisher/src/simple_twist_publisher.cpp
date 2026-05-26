#include <ros/ros.h>
#include <geometry_msgs/Twist.h>
#include <iostream>

using std::cin;
using std::cout;
using std::endl;

#define DEBUG

int main(int argc, char **argv)
{
    ros::init(argc, argv, "simple_twist_publisher");
    ros::NodeHandle nh;
    ros::Publisher pub = nh.advertise<geometry_msgs::Twist>("/dlv/cmd_vel", 1);
    while (ros::ok())
    {
        cout << "Enter linear velocity: ";
        double linear;
        cin >> linear;
        cout << "Enter angular velocity: ";
        double angular;
        cin >> angular;
        geometry_msgs::Twist msg;
        msg.linear.x = linear;
        msg.angular.z = angular;
        pub.publish(msg);
        ros::spinOnce();
    }
    return 0;
}