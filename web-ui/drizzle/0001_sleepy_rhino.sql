CREATE TABLE `channels` (
	`id` varchar(64) NOT NULL,
	`configId` varchar(64) NOT NULL,
	`enabled` enum('yes','no') NOT NULL DEFAULT 'yes',
	`description` varchar(255) NOT NULL,
	`frequencyHz` varchar(20) NOT NULL,
	`ssrc` varchar(20) NOT NULL,
	`sampleRate` varchar(10) DEFAULT '12000',
	`processor` varchar(50) DEFAULT 'grape',
	`createdAt` timestamp DEFAULT (now()),
	CONSTRAINT `channels_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `configurations` (
	`id` varchar(64) NOT NULL,
	`userId` varchar(64) NOT NULL,
	`name` varchar(255) NOT NULL,
	`callsign` varchar(20) NOT NULL,
	`gridSquare` varchar(10) NOT NULL,
	`stationId` varchar(20) NOT NULL,
	`instrumentId` varchar(10) NOT NULL,
	`description` text,
	`dataDir` varchar(500),
	`archiveDir` varchar(500),
	`pswsEnabled` enum('yes','no') NOT NULL DEFAULT 'no',
	`pswsServer` varchar(255) DEFAULT 'pswsnetwork.eng.ua.edu',
	`createdAt` timestamp DEFAULT (now()),
	`updatedAt` timestamp DEFAULT (now()),
	CONSTRAINT `configurations_id` PRIMARY KEY(`id`)
);
